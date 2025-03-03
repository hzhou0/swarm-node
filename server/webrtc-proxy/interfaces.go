package main

import (
	"context"
	"errors"
	"fmt"
	"github.com/coreos/go-oidc/v3/oidc"
	"github.com/cretz/bine/tor"
	"github.com/cretz/bine/torutil/ed25519"
	"github.com/gin-contrib/gzip"
	"github.com/gin-gonic/gin"
	"github.com/gin-gonic/gin/binding"
	"github.com/pion/webrtc/v4"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
	"log"
	"net"
	"net/http"
	"sync"
	"time"
	"webrtc-proxy/grpc/go"
)

type WebrtcInterfaceHttp struct {
	webrtcState  *WebrtcState
	tempDir      string
	ginListener  *net.TCPListener
	server       *http.Server
	tor          *tor.Tor
	onionService *tor.OnionService
	serverConfig *pb.HttpServer
	Error        chan error
	sync.Mutex
}

func NewWebrtcHttpInterface(webrtcState *WebrtcState, tempDir string) *WebrtcInterfaceHttp {
	errChan := make(chan error, 1)
	return &WebrtcInterfaceHttp{
		webrtcState: webrtcState,
		tempDir:     tempDir,
		Error:       errChan,
	}
}

func (s *WebrtcInterfaceHttp) Config() *pb.HttpServer {
	s.Lock()
	defer s.Unlock()
	return s.serverConfig
}

func (s *WebrtcInterfaceHttp) Configure(config *pb.HttpServer) (err error) {
	s.Lock()
	if proto.Equal(s.serverConfig, config) {
		return nil
	}
	s.Unlock()

	s.Close()

	s.Lock()
	defer func() {
		s.Unlock()
		if err != nil {
			s.Close()
		}
	}()

	g := gin.Default()
	g.Use(gzip.Gzip(gzip.DefaultCompression))
	err = g.SetTrustedProxies([]string{"127.0.0.1"})
	if err != nil {
		return err
	}
	g.NoRoute(func(c *gin.Context) {
		c.String(http.StatusNotFound, "Not Found")
	})
	g.NoMethod(func(c *gin.Context) {
		c.String(http.StatusMethodNotAllowed, "Method Not Allowed")
	})

	api := g.Group("/api")
	// Debug endpoint to check server state.
	api.GET("/debug", func(c *gin.Context) {
		s.Lock()
		httpData, err := protojson.Marshal(s.serverConfig)
		if err != nil {
			c.String(500, "Error converting to JSON: %v\n", err)
			return
		}
		s.Unlock()
		c.Data(200, "application/json", httpData)
	})

	api.PUT("/webrtc", func(c *gin.Context) {
		offer := pb.WebrtcOffer{}
		err := c.MustBindWith(&offer, binding.ProtoBuf)
		if err != nil {
			c.String(http.StatusBadRequest, err.Error())
			return
		}
		if !offer.HasSrcUuid() {
			c.String(http.StatusBadRequest, "Missing src uuid")
			return
		}
		if !offer.HasLocalTracksSet() {
			c.String(http.StatusBadRequest, "Missing local tracks set")
			return
		}
		if !offer.HasRemoteTracksSet() {
			c.String(http.StatusBadRequest, "Missing remote tracks set")
			return
		}
		if offer.HasSdp() && offer.HasType() && offer.HasLocalTracksSet() &&
			offer.HasRemoteTracksSet() && offer.GetLocalTracksSet() && offer.GetRemoteTracksSet() {
			// Process Step 3 Request
			// Validate Local/Incoming Tracks
			lTracks := offer.GetLocalTracks()
			for _, lTrack := range lTracks {
				k := NamedTrackKeyFromProto(lTrack)
				if allowed, _ := s.webrtcState.InTrackAllowed(k); !allowed {
					c.String(http.StatusNotAcceptable, "Incoming track %v not allowed", lTrack.GetTrackId())
					return
				}
			}
			// Validate Outgoing/Remote Tracks
			rTracks := offer.GetRemoteTracks()

			s.webrtcState.outTracksMu.RLock()
			outTracks := make(map[NamedTrackKey]LocalhostPort)
			for _, oTrack := range rTracks {
				k := NamedTrackKeyFromProto(oTrack)
				if tr, exists := s.webrtcState.outTrackStates[k]; !exists || !tr.broadcast {
					c.String(http.StatusNotAcceptable, "Requested track %v not available", oTrack.GetTrackId())
					return
				} else {
					outTracks[k] = tr.port
				}
			}
			s.webrtcState.outTracksMu.RUnlock()
			pOffer := PeeringOffer{
				peerId:      offer.GetSrcUuid(),
				sdp:         &webrtc.SessionDescription{Type: webrtc.NewSDPType(offer.GetType()), SDP: offer.GetSdp()},
				outTracks:   outTracks,
				inTracks:    Map(lTracks, NamedTrackKeyFromProto),
				dataChannel: offer.GetDatachannel(),
			}
			s.webrtcState.UnPeer(pOffer.peerId)
			answerSdp, err := s.webrtcState.Peer(pOffer, 0)
			if err != nil {
				c.String(http.StatusInternalServerError, "Peering failed %v", err)
				return
			}
			answer := pb.WebrtcOffer{}
			c.Request.URL.Fragment = ""
			c.Request.URL.RawQuery = ""
			c.Request.URL.Host = c.Request.Host
			c.Request.URL.Scheme = "http"
			answer.SetSrcUuid(c.Request.URL.String())
			answer.SetLocalTracks(rTracks)
			answer.SetLocalTracksSet(true)
			answer.SetRemoteTracks(lTracks)
			answer.SetRemoteTracksSet(true)
			answer.SetSdp(answerSdp.SDP)
			answer.SetType(answerSdp.Type.String())
			c.Header("Content-Type", "application/x-protobuf")
			c.ProtoBuf(http.StatusOK, &answer)
			return
		}
		if offer.HasLocalTracksSet() {
			// Process Step 1 Request
			var allowedRemote []*pb.NamedTrack
			answer := pb.WebrtcOffer{}
			c.Request.URL.Fragment = ""
			c.Request.URL.RawQuery = ""
			c.Request.URL.Host = c.Request.Host
			c.Request.URL.Scheme = "http"
			answer.SetSrcUuid(c.Request.URL.String())
			for _, track := range offer.GetLocalTracks() {
				ntk := NamedTrackKeyFromProto(track)
				if allowed, _ := s.webrtcState.InTrackAllowed(ntk); allowed {
					allowedRemote = append(allowedRemote, track)
				}
			}
			answer.SetRemoteTracks(allowedRemote)
			answer.SetRemoteTracksSet(true)
			answer.SetLocalTracks(Map(s.webrtcState.BroadcastOutTracks(), NamedTrackKey.toProto))
			answer.SetLocalTracksSet(true)
			c.Header("Content-Type", "application/x-protobuf")
			c.ProtoBuf(http.StatusOK, &answer)
			return
		}
	})
	api.DELETE("/webrtc", func(c *gin.Context) {
		offer := pb.WebrtcOffer{}
		err := c.MustBindWith(&offer, binding.ProtoBuf)
		if err != nil {
			c.String(http.StatusBadRequest, err.Error())
			return
		}
		if !offer.HasSrcUuid() {
			c.String(http.StatusBadRequest, "No source UUID")
			return
		}
		s.webrtcState.UnPeer(offer.GetSrcUuid())
		c.String(http.StatusNoContent, "")
		return
	})

	// Create a TCP listener for gin
	if !config.HasAddress() {
		return fmt.Errorf("address not set")
	}
	tcpAddr, err := net.ResolveTCPAddr("tcp", config.GetAddress())
	if err != nil {
		return err
	}
	s.ginListener, err = net.ListenTCP("tcp", tcpAddr)
	if err != nil {
		return err
	}

	switch config.WhichAuth() {
	case pb.HttpServer_Auth_not_set_case:
	case pb.HttpServer_OnionServiceV3Auth_case:
		log.Println("Exposing /api requests to onion service")
		onionAuth := config.GetOnionServiceV3Auth()
		if !onionAuth.HasHsEd25519SecretKey() {
			return fmt.Errorf("secret key not set")
		}
		if len(onionAuth.GetHsEd25519SecretKey()) != 96 {
			return fmt.Errorf("secret key must be 96 bytes")
		}
		secKey := ed25519.PrivateKey(onionAuth.GetHsEd25519SecretKey()[32:]).KeyPair()

		var torArgs []string
		if !onionAuth.GetAnonymous() {
			torArgs = []string{
				"--HiddenServiceSingleHopMode", "1",
				"--HiddenServiceNonAnonymousMode", "1",
				"--SocksPort", "0",
			}
		}
		s.tor, err = tor.Start(context.Background(), &tor.StartConf{
			TempDataDirBase:   s.tempDir,
			RetainTempDataDir: false,
			EnableNetwork:     true,
			ExtraArgs:         torArgs,
			NoAutoSocksPort:   !onionAuth.GetAnonymous(),
			NoHush:            true,
		})
		if err != nil {
			return err
		}
		listenCtx, listenCancel := context.WithTimeout(context.Background(), 1*time.Minute)
		defer listenCancel()
		s.onionService, err = s.tor.Listen(listenCtx, &tor.ListenConf{
			Key:           secKey,
			LocalListener: s.ginListener,
			RemotePorts:   []int{80, s.ginListener.Addr().(*net.TCPAddr).Port},
			Version3:      true,
			NonAnonymous:  !onionAuth.GetAnonymous(),
		})
		if err != nil {
			return err
		}

	case pb.HttpServer_CloudflareAuth_case:
		log.Println("Expecting /api requests to have cloudflare headers")
		cfAuth := config.GetCloudflareAuth()
		if cfAuth.HasTeamDomain() {
			return fmt.Errorf("cloudflare team domain is not set")
		}
		if cfAuth.HasTeamAud() {
			return fmt.Errorf("cloudflare team aud is not set")
		}
		cloudflareDomain := cfAuth.GetTeamDomain()
		cloudflareAUD := cfAuth.GetTeamAud()
		api.Use(func(c *gin.Context) {
			// Extract the token from the header
			accessJWT := c.GetHeader("Cf-Access-Jwt-Assertion")
			if accessJWT == "" {
				c.JSON(http.StatusUnauthorized, gin.H{"error": "No token on the request"})
				c.Abort()
			}

			// Verify the token
			ctx := c.Request.Context()
			certsURL := fmt.Sprintf("%s/cdn-cgi/access/certs", cloudflareDomain)
			config := &oidc.Config{
				ClientID: cloudflareAUD,
			}
			keySet := oidc.NewRemoteKeySet(ctx, certsURL)
			verifier := oidc.NewVerifier(cloudflareDomain, keySet, config)
			_, err := verifier.Verify(ctx, accessJWT)
			if err != nil {
				c.JSON(http.StatusUnauthorized, gin.H{"error": fmt.Sprintf("Invalid token: %s", err.Error())})
				c.Abort()
			}
			c.Next()
		})
	}

	server := &http.Server{
		Handler: g,
	}
	ginListener := s.ginListener
	go func() {
		if err := server.Serve(ginListener); !errors.Is(err, http.ErrServerClosed) {
			log.Printf("Error serving: %v\n", err)
			s.Close()
			s.Error <- err
		}
	}()
	s.server = server
	s.serverConfig = config
	return nil
}

func (s *WebrtcInterfaceHttp) Close() {
	log.Println("Closing http interface")
	s.Lock()
	defer s.Unlock()
	if s.server != nil {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if err := s.server.Shutdown(ctx); err != nil {
			log.Printf("Error shutting down server %v\n", err)
		} else {
			s.server = nil
			log.Println("Server closed")
		}
	}
	if s.onionService != nil {
		err := s.onionService.LocalListener.Close()
		if err != nil {
			log.Printf("Error closing onion service %v\n", err)
		} else {
			log.Println("Onion service closed")
		}
		s.onionService = nil
	}
	if s.ginListener != nil {
		err := s.ginListener.Close()
		if err != nil {
			log.Printf("Error closing gin listener %v\n", err)
		} else {
			log.Println("Gin listener closed")
		}
	}
	if s.tor != nil {
		err := s.tor.Close()
		if err != nil {
			log.Printf("Error closing tor %v\n", err)
		} else {
			log.Println("Tor process closed")
			s.tor = nil
		}
	}
}
