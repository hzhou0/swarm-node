package main

import (
	"context"
	"errors"
	"fmt"
	"github.com/coreos/go-oidc/v3/oidc"
	"github.com/gin-contrib/gzip"
	"github.com/gin-gonic/gin"
	"github.com/gin-gonic/gin/binding"
	"github.com/pion/webrtc/v4"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
	"log"
	"net/http"
	"sync"
	"time"
	"webrtc-proxy/grpc/go"
)

type WebrtcInterfaceHttp struct {
	webrtcState  *WebrtcState
	engine       *gin.Engine
	server       *http.Server
	serverMu     sync.Mutex
	serverConfig *pb.HttpServer
	Error        chan error
}

func NewWebrtcHttpInterface(webrtcState *WebrtcState) *WebrtcInterfaceHttp {
	errChan := make(chan error, 1)
	return &WebrtcInterfaceHttp{
		webrtcState: webrtcState,
		Error:       errChan,
	}
}

func (s *WebrtcInterfaceHttp) Configure(config *pb.HttpServer) error {
	s.serverMu.Lock()
	if proto.Equal(s.serverConfig, config) {
		return nil
	}
	s.serverMu.Unlock()
	s.Close()
	s.serverMu.Lock()
	defer s.serverMu.Unlock()

	g := gin.Default()
	g.Use(gzip.Gzip(gzip.DefaultCompression))
	err := g.SetTrustedProxies([]string{"127.0.0.1"})
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
	switch config.WhichAuth() {
	case pb.HttpServer_Auth_not_set_case:
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

	// Debug endpoint to check server state.
	api.GET("/debug", func(c *gin.Context) {
		s.serverMu.Lock()
		httpData, err := protojson.Marshal(s.serverConfig)
		if err != nil {
			c.String(500, "Error converting to JSON: %v\n", err)
			return
		}
		s.serverMu.Unlock()
		c.JSON(http.StatusOK, httpData)
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

	if !config.HasAddress() {
		return fmt.Errorf("address not set")
	}
	s.server = &http.Server{
		Addr:    config.GetAddress(),
		Handler: g.Handler(),
	}
	s.serverConfig = config
	go func() {
		if err := s.server.ListenAndServe(); !errors.Is(err, http.ErrServerClosed) {
			log.Printf("Error serving: %v\n", err)
			s.Close()
			s.Error <- err
		}
	}()
	return nil

}

func (s *WebrtcInterfaceHttp) Close() {
	s.serverMu.Lock()
	defer s.serverMu.Unlock()
	if s.server != nil {
		ctx, cancel := context.WithTimeout(context.Background(), 1*time.Second)
		defer cancel()
		if err := s.server.Shutdown(ctx); err != nil {
			log.Printf("Error shutting down server %v\n", err)
		}
		s.server = nil
		log.Println("Server closed")
	}
}
