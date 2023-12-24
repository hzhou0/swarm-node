package main

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/cloudflare/cloudflare-go"
	"log"
	"math/rand"
	"os"
	"os/exec"
	"strings"
	"time"
)

//go:embed data/names.txt
var _names string
var nameList = strings.Split(strings.TrimSpace(_names), "\n")

type CfProperties struct {
	AccountId  string `json:"accountId"`
	ZoneId     string `json:"zoneId"`
	AudTag     string `json:"audTag"`
	RootDomain string `json:"rootDomain"`
}

type CfTokenConfig struct {
	TunnelDnsWriteApiToken string `json:"TunnelDnsWriteApiToken"`
	CfProperties
}

type CfTunnelConfig struct {
	TunnelToken string `json:"tunnelToken"`
	CfProperties
}

func run(timeout time.Duration, name string, arg ...string) error {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	cmdCtx := exec.CommandContext(ctx, name, arg...)
	return cmdCtx.Run()
}

func readCfConfigFile[V CfTokenConfig | CfTunnelConfig](path string) *V {
	fileInfo, err := os.Stat(path)
	if err != nil {
		if !os.IsNotExist(err) {
			log.Printf("Error on os.stat: %v\n", err)
		}
		return nil
	}
	if fileInfo.IsDir() {
		log.Fatalf("%s is folder, should be json file", path)
	}
	file, err := os.Open(fileInfo.Name())
	if err != nil {
		log.Printf("Error on Opening file: %v\n", err)
		return nil
	}
	defer file.Close()
	decoder := json.NewDecoder(file)
	var cfConf V
	err = decoder.Decode(&cfConf)
	if err != nil {
		log.Printf("Error on Decoding file: %v\n", err)
		return nil
	} else {
		return &cfConf
	}
}

func cloudflareSetupOrPanic(cfTokenConfPath string, cfTunnelConfPath string) {
	systemctl, err := exec.LookPath("systemctl")
	if err != nil {
		panic("systemctl not found")
	}
	cloudflared, err := exec.LookPath("cloudflared")
	if err != nil {
		panic("cloudflared not found")
	}

	cfTokenConf := readCfConfigFile[CfTokenConfig](cfTokenConfPath)
	if cfTokenConf != nil {
		tunnelToken, resources, err := createTunnel(*cfTokenConf)
		if err == nil {
			tunnelConfFile, e := os.Create(cfTunnelConfPath)
			if e != nil {
				_ = deleteResources(resources)
				panic(e)
			}
			defer tunnelConfFile.Close()
			encoder := json.NewEncoder(tunnelConfFile)
			cfTunnelConf := CfTunnelConfig{
				TunnelToken:  tunnelToken,
				CfProperties: cfTokenConf.CfProperties,
			}
			e = encoder.Encode(cfTunnelConf)
			if e != nil {
				_ = deleteResources(resources)
				panic(e)
			}
			e = os.Remove(cfTokenConfPath)
			if e != nil {
				_ = deleteResources(resources)
				panic(e)
			}
			e = run(5*time.Second, "sudo", cloudflared, "service", "install", tunnelToken)
			if e != nil {
				panic(e)
			}
		}
	}

	err = run(5*time.Second, systemctl, "status", "cloudflared")
	if err != nil {
		var exitError *exec.ExitError
		if errors.As(err, &exitError) {
			log.Printf("Assuming cloudflared needs restart, exit code: %d, output: %s", exitError.ExitCode(), exitError.Stderr)
			cfTunnel := readCfConfigFile[CfTunnelConfig](cfTunnelConfPath)
			if cfTunnel == nil {
				panic("cloudflared failed and no tunnel config, exiting")
			}
			_ = run(5*time.Second, "sudo", cloudflared, "service", "uninstall")
			err = run(5*time.Second, "sudo", cloudflared, "service", "install", cfTunnel.TunnelToken)
			if err != nil {
				panic(err)
			}
		} else {
			panic(err)
		}
	}
}

type TunnelResources struct {
	cfConf    CfTokenConfig
	Tunnel    *cloudflare.Tunnel
	DNSRecord *cloudflare.DNSRecord
}

func createTunnel(cfConf CfTokenConfig) (string, TunnelResources, error) {
	resources := TunnelResources{
		cfConf: cfConf,
	}
	cf, err := cloudflare.NewWithAPIToken(cfConf.TunnelDnsWriteApiToken)
	if err != nil {
		return "", resources, err
	}
	ctx := context.Background()
	account := cloudflare.AccountIdentifier(cfConf.AccountId)
	zone := cloudflare.ZoneIdentifier(cfConf.ZoneId)

	name := ""
	domain := ""
	for {
		name = fmt.Sprintf("%s-node", strings.ToLower(nameList[rand.Intn(len(nameList))]))
		_, tunnelRes, e := cf.ListTunnels(ctx, account, cloudflare.TunnelListParams{
			IsDeleted: cloudflare.BoolPtr(false),
			Name:      name,
		})
		if e != nil {
			return "", resources, err
		}
		domain = fmt.Sprintf("%s.%s", name, cfConf.RootDomain)
		_, recordRes, e := cf.ListDNSRecords(ctx, zone, cloudflare.ListDNSRecordsParams{
			Name: domain,
		})
		if e != nil {
			return "", resources, e
		}
		if tunnelRes.Count == 0 && recordRes.Count == 0 {
			break
		}
	}

	*resources.Tunnel, err = cf.CreateTunnel(ctx, account, cloudflare.TunnelCreateParams{
		Name:      name,
		ConfigSrc: "cloudflare",
	})
	if err != nil {
		return "", resources, err
	}

	_, err = cf.UpdateTunnelConfiguration(ctx, account, cloudflare.TunnelConfigurationParams{
		TunnelID: resources.Tunnel.ID,
		Config: cloudflare.TunnelConfiguration{
			OriginRequest: cloudflare.OriginRequestConfig{
				Access: &cloudflare.AccessConfig{
					Required: true,
					AudTag:   []string{cfConf.AudTag},
				},
			},
			Ingress: []cloudflare.UnvalidatedIngressRule{
				{
					Service:  "http://localhost:7777",
					Hostname: domain,
				},
				{
					Service:  "http://localhost:7778",
					Hostname: domain,
					Path:     "admin",
				},
				{
					Service: "http_status:404",
				},
			},
		},
	})
	if err != nil {
		return "", resources, err
	}
	*resources.DNSRecord, err = cf.CreateDNSRecord(ctx, zone, cloudflare.CreateDNSRecordParams{
		Content:   fmt.Sprintf("%s.cfargotunnel.com", resources.Tunnel.ID),
		Type:      "CNAME",
		Name:      domain,
		Proxiable: true,
	})
	if err != nil {
		return "", resources, err
	}
	token, err := cf.GetTunnelToken(ctx, account, resources.Tunnel.ID)
	return token, resources, err
}

func deleteResources(resources TunnelResources) error {
	cf, err := cloudflare.NewWithAPIToken(resources.cfConf.TunnelDnsWriteApiToken)
	if err != nil {
		return err
	}
	ctx := context.Background()
	if resources.DNSRecord != nil {
		zone := cloudflare.ZoneIdentifier(resources.cfConf.ZoneId)
		e := cf.DeleteDNSRecord(ctx, zone, resources.DNSRecord.ID)
		if e != nil {
			return e
		}
	}
	if resources.Tunnel != nil {
		account := cloudflare.AccountIdentifier(resources.cfConf.AccountId)
		e := cf.DeleteTunnel(ctx, account, resources.DNSRecord.ID)
		if e != nil {
			return e
		}
	}
	return nil
}
