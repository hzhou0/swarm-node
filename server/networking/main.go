//go:build linux

package main

import (
	"fmt"
	"github.com/coreos/go-oidc/v3/oidc"
	"github.com/gin-contrib/gzip"
	"github.com/gin-gonic/gin"
	"github.com/gin-gonic/gin/binding"
	"github.com/pion/webrtc/v4"
	"log"
	"net"
	"net/http"
	"networking/ipc"
	"os"
)

func runHttpServer(webrtcState *WebrtcState, addr string) {
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
			var inTracks []NamedTrackKey
			for _, lTrack := range lTracks {
				k := NewNamedTrackKey("", lTrack.GetTrackId(), lTrack.GetStreamId(), lTrack.GetMimeType())
				if !webrtcState.InTrackAllowed(k) {
					c.String(http.StatusNotAcceptable, "Incoming track %v not allowed", lTrack.GetTrackId())
					return
				} else {
					inTracks = append(inTracks, k)
				}
			}
			// Validate Outgoing/Remote Tracks
			rTracks := offer.GetRemoteTracks()
			var outTracks []NamedTrackKey
			for _, oTrack := range rTracks {
				k := NewNamedTrackKey("", oTrack.GetTrackId(), oTrack.GetStreamId(), oTrack.GetMimeType())
				if !webrtcState.OutTrackAllowed(k) {
					c.String(http.StatusNotAcceptable, "Outbound track %v not allowed", oTrack.GetTrackId())
					return
				} else {
					outTracks = append(outTracks, k)
				}
			}
			pOffer := NewPeeringOffer(
				offer.GetSrcUuid(),
				&webrtc.SessionDescription{Type: webrtc.NewSDPType(offer.GetType()), SDP: offer.GetSdp()},
				outTracks,
				inTracks,
			)
			webrtcState.UnPeer(pOffer.peerId)
			err, answerSdp := webrtcState.Peer(*pOffer)
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
				if webrtcState.InTrackAllowed(NewNamedTrackKey("", track.GetTrackId(), track.GetStreamId(), track.GetMimeType())) {
					allowedRemote = append(allowedRemote, track)
				}
			}
			answer.SetRemoteTracks(allowedRemote)
			answer.SetRemoteTracksSet(true)
			var localTracks []*ipc.NamedTrack
			for _, v := range webrtcState.OutTracks() {
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
	l, err := net.Listen("tcp", addr)
	if err != nil {
		panic(err)
	}
	go func() {
		err := s.RunListener(l)
		if err != nil {
			panic(err)
		}
	}()
}

func main() {
	webrtcState := NewWebrtcState()
	go runHttpServer(webrtcState, ":8080")
	select {}
	_, eventR := runKernelBackground()
	go handleKernelEvents(eventR)
	select {}
}
