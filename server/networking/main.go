//go:build linux

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
	"log"
	"net/http"
	"networking/ipc"
	"os"
	"slices"
	"time"
)

func runHttpServer(webrtcState *WebrtcState, addr string) func() {
	s := gin.Default()
	s.Use(gzip.Gzip(gzip.DefaultCompression))
	err := s.SetTrustedProxies([]string{"127.0.0.1"})
	if err != nil {
		panic(err)
	}
	s.NoRoute(func(c *gin.Context) {
		c.String(http.StatusNotFound, "Not Found")
	})
	s.NoMethod(func(c *gin.Context) {
		c.String(http.StatusMethodNotAllowed, "Method Not Allowed")
	})

	api := s.Group("/api")
	cloudflareDomain := os.Getenv("CF_TEAM_DOMAIN")
	cloudflareAUD := os.Getenv("CF_TEAM_AUD")
	if cloudflareDomain != "" && cloudflareAUD != "" {
		log.Println("Expecting /api requests to have cloudflare headers")
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
	} else {
		log.Println("Warning: API unprotected.")
	}

	api.PUT("/webrtc", func(c *gin.Context) {
		offer := ipc.WebrtcOffer{}
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
				if !webrtcState.InTrackAllowed(k) {
					c.String(http.StatusNotAcceptable, "Incoming track %v not allowed", lTrack.GetTrackId())
					return
				}
			}
			// Validate Outgoing/Remote Tracks
			broadcasts := webrtcState.BroadcastOutTracks()
			rTracks := offer.GetRemoteTracks()
			for _, oTrack := range rTracks {
				k := NamedTrackKeyFromProto(oTrack)
				if !slices.Contains(broadcasts, k) {
					c.String(http.StatusNotAcceptable, "Requested track %v not available", oTrack.GetTrackId())
					return
				}
			}
			pOffer := PeeringOffer{
				peerId:      offer.GetSrcUuid(),
				sdp:         &webrtc.SessionDescription{Type: webrtc.NewSDPType(offer.GetType()), SDP: offer.GetSdp()},
				outTracks:   Map(rTracks, NamedTrackKeyFromProto),
				inTracks:    Map(lTracks, NamedTrackKeyFromProto),
				dataChannel: offer.GetDatachannel(),
			}
			webrtcState.UnPeer(pOffer.peerId)
			answerSdp, err := webrtcState.Peer(pOffer, 0)
			if err != nil {
				c.String(http.StatusInternalServerError, "Peering failed %v", err)
				return
			}
			answer := ipc.WebrtcOffer{}
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
			var allowedRemote []*ipc.NamedTrack
			answer := ipc.WebrtcOffer{}
			c.Request.URL.Fragment = ""
			c.Request.URL.RawQuery = ""
			c.Request.URL.Host = c.Request.Host
			c.Request.URL.Scheme = "http"
			answer.SetSrcUuid(c.Request.URL.String())
			for _, track := range offer.GetLocalTracks() {
				ntk := NamedTrackKeyFromProto(track)
				if webrtcState.InTrackAllowed(ntk) {
					allowedRemote = append(allowedRemote, track)
				}
			}
			answer.SetRemoteTracks(allowedRemote)
			answer.SetRemoteTracksSet(true)
			var localTracks []*ipc.NamedTrack
			for _, v := range webrtcState.BroadcastOutTracks() {
				tr := ipc.NamedTrack{}
				tr.SetStreamId(v.streamId)
				tr.SetTrackId(v.trackId)
				tr.SetMimeType(v.mimeType)
				localTracks = append(localTracks, &tr)
			}
			answer.SetLocalTracks(localTracks)
			answer.SetLocalTracksSet(true)
			c.Header("Content-Type", "application/x-protobuf")
			c.ProtoBuf(http.StatusOK, &answer)
			return
		}
	})
	api.DELETE("/webrtc", func(c *gin.Context) {
		offer := ipc.WebrtcOffer{}
		err := c.MustBindWith(&offer, binding.ProtoBuf)
		if err != nil {
			c.String(http.StatusBadRequest, err.Error())
			return
		}
		if !offer.HasSrcUuid() {
			c.String(http.StatusBadRequest, "No source UUID")
			return
		}
		webrtcState.UnPeer(offer.GetSrcUuid())
		c.String(http.StatusNoContent, "")
		return
	})
	server := &http.Server{
		Addr:    addr,
		Handler: s.Handler(),
	}
	go func() {
		if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			panic(err)
		}
	}()
	return func() {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if err := server.Shutdown(ctx); err != nil {
			log.Printf("Error shutting down server %v\n", err)
		}
	}
}

func drainChannel[T any](ch <-chan T) {
	for {
		select {
		case _, ok := <-ch:
			if !ok {
				return // Stop when the channel is closed
			}
		default:
			return // Stop when the channel is empty
		}
	}
}
func main() {
	webrtcConfig := WebrtcStateConfig{
		webrtcConfig: webrtc.Configuration{
			ICEServers: []webrtc.ICEServer{
				{
					URLs: []string{"stun:stun.l.google.com:19302"},
				},
			},
		},
		reconnectAttempts: 0,
		allowedInTracks:   []NamedTrackKey{},
	}
	webrtcState := NewWebrtcState(webrtcConfig)
	cancelServer := func() {}
	serverAddr := ""
	serverRunning := false

	achievedState := make(chan *ipc.State)
	kernel, err := NewKernel(webrtcState.DataOut, webrtcState.DataIn, webrtcState.MediaIn, achievedState)
	if err != nil {
		panic(err)
	}
	for {
		select {
		case newState := <-kernel.TargetState:
			if newState.HasHttpAddr() && (serverAddr != newState.GetHttpAddr() || (!serverRunning)) {
				cancelServer()
				serverAddr = newState.GetHttpAddr()
				cancelServer = runHttpServer(webrtcState, serverAddr)
				serverRunning = true
			} else if serverRunning {
				cancelServer()
				cancelServer = func() {}
				serverRunning = false
			}

			err := webrtcState.Reconcile(newState)
			if err != nil {
				panic(err)
			}
			stateMsg, err := webrtcState.ToProto()
			if err != nil {
				panic(err)
			}
			achievedState <- stateMsg
		case <-webrtcState.backgroundChange:
			drainChannel(webrtcState.backgroundChange)
			stateMsg, err := webrtcState.ToProto()
			if err != nil {
				panic(err)
			}
			achievedState <- stateMsg
		}
	}
}
