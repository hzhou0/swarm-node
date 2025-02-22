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
	"github.com/go-gst/go-gst/gst"
	"github.com/go-resty/resty/v2"
	"github.com/pion/webrtc/v4"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/local"
	"google.golang.org/grpc/keepalive"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path"
	"path/filepath"
	"sync"
	"syscall"
	"time"
	"webrtc-proxy/grpc/go"
)

type IDPool struct {
	sync.Mutex
	ids map[string]struct{}
}

func NewIDPool() IDPool {
	return IDPool{ids: map[string]struct{}{}}
}

func (p *IDPool) Claim() UUID {
	p.Lock()
	i := 4
	id := NewUUID(i)
	for _, exists := p.ids[id]; exists; i++ {
		id = NewUUID(i)
	}
	p.Unlock()
	return id
}

func (p *IDPool) Release(id UUID) {
	p.Lock()
	delete(p.ids, id)
	p.Unlock()
}

type WebrtcHttpInterfaceState struct {
	webrtcState  *WebrtcState
	engine       *gin.Engine
	server       *http.Server
	serverMu     sync.Mutex
	serverConfig *pb.HttpServer
	Error        chan error
}

func (s *WebrtcHttpInterfaceState) Configure(config *pb.HttpServer) error {
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
				if !s.webrtcState.InTrackAllowed(k) {
					c.String(http.StatusNotAcceptable, "Incoming track %v not allowed", lTrack.GetTrackId())
					return
				}
			}
			// Validate Outgoing/Remote Tracks
			rTracks := offer.GetRemoteTracks()

			s.webrtcState.outTracksMu.RLock()
			outTracks := make(map[NamedTrackKey]SocketFilename)
			for _, oTrack := range rTracks {
				k := NamedTrackKeyFromProto(oTrack)
				if tr, exists := s.webrtcState.outTrackStates[k]; !exists || !tr.broadcast {
					c.String(http.StatusNotAcceptable, "Requested track %v not available", oTrack.GetTrackId())
					return
				} else {
					outTracks[k] = tr.socket
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
				if s.webrtcState.InTrackAllowed(ntk) {
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

func (s *WebrtcHttpInterfaceState) Close() {
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

func NewWebrtcHttpServer(webrtcState *WebrtcState) *WebrtcHttpInterfaceState {
	errChan := make(chan error, 1)
	return &WebrtcHttpInterfaceState{
		webrtcState: webrtcState,
		Error:       errChan,
	}
}

func drainChannel[T any](ch <-chan T) T {
	for {
		var val T
		var ok bool
		select {
		case val, ok = <-ch:
			if !ok {
				return val // Stop when the channel is closed
			}
		default:
			return val // Stop when the channel is empty
		}
	}
}

type webrtcProxyServer struct {
	pb.UnimplementedWebrtcProxyServer
	defaultConfig WebrtcStateConfig
	idPool        IDPool
}

func newWebrtcProxyServer() *webrtcProxyServer {
	webrtcConfig := WebrtcStateConfig{
		webrtcConfig: webrtc.Configuration{
			ICEServers: []webrtc.ICEServer{
				{
					URLs: []string{"stun:stun.l.google.com:19302"},
				},
			},
		},
		client:            resty.New(),
		reconnectAttempts: 0,
		allowedInTracks:   []NamedTrackKey{},
	}
	return &webrtcProxyServer{defaultConfig: webrtcConfig, idPool: NewIDPool()}
}

func (s *webrtcProxyServer) Connect(stream pb.WebrtcProxy_ConnectServer) error {
	connUUID := s.idPool.Claim()
	defer s.idPool.Release(connUUID)
	runtimeDir := os.Getenv("RUNTIME_DIRECTORY")
	if runtimeDir == "" {
		return fmt.Errorf("RUNTIME_DIRECTORY is not set")
	}
	webrtcState, err := NewWebrtcState(s.defaultConfig, path.Join(runtimeDir, "s", connUUID), path.Join(runtimeDir, "c", connUUID))
	if err != nil {
		return err
	}
	defer webrtcState.Close()
	ev := pb.Event_builder{
		MediaSocketDirs: pb.MediaSocketDirs_builder{
			ServerDir: proto.String(webrtcState.ServerMediaSocketDir),
			ClientDir: proto.String(webrtcState.ClientMediaSocketDir),
		}.Build(),
	}.Build()
	if err = stream.Send(ev); err != nil {
		return err
	}

	setState := make(chan *pb.State)
	achievedState := make(chan *pb.State)

	errChan := make(chan error)
	httpServer := NewWebrtcHttpServer(webrtcState)
	defer httpServer.Close()
	go func() {
		for {
			select {
			case <-stream.Context().Done():
				return
			default:
			}

			mutation, err := stream.Recv()
			if err == io.EOF {
				errChan <- nil
				return
			}
			if err != nil {
				errChan <- err
				return
			}
			switch mutation.WhichMutation() {
			case pb.Mutation_Data_case:
				webrtcState.DataOut <- mutation.GetData()
			case pb.Mutation_SetState_case:
				setState <- mutation.GetSetState()
			case pb.Mutation_Mutation_not_set_case:
			default:
				errChan <- fmt.Errorf("unknown mutation type: %v", mutation.WhichMutation())
				return
			}
		}
	}()
	go func() {
		for {
			ev := pb.Event{}
			select {
			case data := <-webrtcState.DataIn:
				ev.SetData(data)
			case media := <-webrtcState.MediaIn:
				ev.SetMedia(media)
			case state := <-achievedState:
				ev.SetAchievedState(state)
			case <-stream.Context().Done():
				return
			}
			err := stream.Send(&ev)
			if err != nil {
				errChan <- err
				return
			}
		}
	}()
	for {
		select {
		case err := <-errChan:
			return err
		case newState := <-setState:
			if latestState := drainChannel(setState); latestState != nil {
				newState = latestState
			}
			if newState.HasHttpServerConfig() {
				err := httpServer.Configure(newState.GetHttpServerConfig())
				if err != nil {
					go func() {
						httpServer.Error <- err
					}()
				}
			} else {
				httpServer.Close()
			}
			err := webrtcState.Reconcile(newState)
			if err != nil {
				log.Printf("Error reconciling state: %v", err)
				return err
			}
			stateMsg, err := webrtcState.ToProto(httpServer)
			if err != nil {
				log.Printf("Error converting state to proto: %v", err)
				return err
			}
			achievedState <- stateMsg
		case <-webrtcState.BackgroundChange:
			stateMsg, err := webrtcState.ToProto(httpServer)
			if err != nil {
				log.Printf("Error converting state to proto: %v", err)
				return err
			}
			achievedState <- stateMsg
		case <-httpServer.Error:
			stateMsg, err := webrtcState.ToProto(httpServer)
			if err != nil {
				log.Printf("Error converting state to proto: %v", err)
				return err
			}
			achievedState <- stateMsg
		}
	}
}

func debugTools(runtimeDir string, ctx context.Context, wg *sync.WaitGroup) {
	defer wg.Done()
	debugSendVideo := os.Getenv("DEBUG_SEND_VIDEO")
	if debugSendVideo != "" {
		var encodeStr string
		switch debugSendVideo {
		case "video/h264":
			encodeStr = "x264enc speed-preset=ultrafast tune=zerolatency key-int-max=1"
		case "video/h265":
			encodeStr = "x265enc speed-preset=ultrafast tune=zerolatency key-int-max=1"
		case "video/vp9":
			encodeStr = "vp9enc deadline=1"
		default:
			log.Printf("Unknown debug video type: %s\n", debugSendVideo)
			return
		}
		log.Println("DEBUG_SEND_VIDEO is set, setting up WebRTC state to stream test video")
		config := WebrtcStateConfig{
			webrtcConfig: webrtc.Configuration{
				ICEServers: []webrtc.ICEServer{
					{
						URLs: []string{"stun:stun.l.google.com:19302"},
					},
				},
			},
			reconnectAttempts: 0,
			client:            resty.New(),
			allowedInTracks:   []NamedTrackKey{},
		}

		debugState, err := NewWebrtcState(config, path.Join(runtimeDir, "debug-server-media"), path.Join(runtimeDir, "debug-client-media"))
		if err != nil {
			panic(err)
		}
		defer debugState.Close()

		outputTrackKey := NewNamedTrackKey("rgbd", "realsenseD455", debugSendVideo)
		outputTrackKeySocket := "debugSend"
		pf := PeeringOffer{
			peerId:      "http://localhost:8080/api/webrtc",
			sdp:         nil,
			outTracks:   map[NamedTrackKey]SocketFilename{outputTrackKey: outputTrackKeySocket},
			inTracks:    nil,
			dataChannel: false,
		}
		pipelineStr := fmt.Sprintf(
			"videotestsrc is-live=true pattern=smpte ! video/x-raw,width=1920,height=1080,format=I420,framerate=(fraction)30/1 ! %s ! shmsink shm-size=671088640 wait-for-connection=true socket-path=%s",
			encodeStr,
			path.Join(debugState.ClientMediaSocketDir, outputTrackKeySocket),
		)
		pipeline, err := gst.NewPipelineFromString(pipelineStr)
		if err != nil {
			panic(err)
		}
		err = pipeline.Start()
		if err != nil {
			panic(err)
		}

		defer func() {
			log.Println("Stopping debug pipeline")
			err := pipeline.SetState(gst.StateNull)
			if err != nil {
				log.Printf("Error stopping pipeline: %v", err)
			}
			log.Println("Stopped debug state")
		}()

		ticker := time.NewTicker(5 * time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				_, err := debugState.Peer(pf, 0)
				if err != nil {
					log.Printf("Debug State err: %v", err)
				}
			}
		}
	}

	debugRecvVideo := os.Getenv("DEBUG_RECV_VIDEO")
	if debugRecvVideo != "" {
		config := WebrtcStateConfig{
			webrtcConfig: webrtc.Configuration{
				ICEServers: []webrtc.ICEServer{
					{
						URLs: []string{"stun:stun.l.google.com:19302"},
					},
				},
			},
			reconnectAttempts: 0,
			client:            resty.New(),
			allowedInTracks: []NamedTrackKey{
				NewNamedTrackKey("rgbd", "realsenseD455", "video/h265"),
			},
		}

		debugState, err := NewWebrtcState(config, path.Join(runtimeDir, "debug1-server-media"), path.Join(runtimeDir, "debug1-client-media"))
		if err != nil {
			panic(err)
		}
		defer debugState.Close()
		httpServ := NewWebrtcHttpServer(debugState)
		err = httpServ.Configure(pb.HttpServer_builder{
			Address: proto.String("127.0.0.1:9090"),
		}.Build())
		if err != nil {
			panic(err)
		}

		var pipeline *gst.Pipeline
		defer func() {
			if pipeline != nil {
				err := pipeline.SetState(gst.StateNull)
				if err != nil {
					log.Printf("Error stopping pipeline: %v", err)
				}
			}
		}()
		for {
			select {
			case <-ctx.Done():
				return
			case receivedTrack := <-debugState.MediaIn:
				incomingTrack := NamedTrackKeyFromProto(receivedTrack.GetTrack())
				var decodeStr string
				switch incomingTrack.mimeType {
				case "video/h264":
					decodeStr = "queue ! h264parse ! avdec_h264"
				case "video/h265":
					decodeStr = "queue ! h265parse ! avdec_h265"
				default:
					log.Printf("Unknown debug video type: %s\n", debugSendVideo)
					return
				}
				pipelineStr := fmt.Sprintf(
					"shmsrc socket-path=%s is-live=true do-timestamp=true ! %s ! autovideosink sync=false",
					path.Join(debugState.ServerMediaSocketDir, receivedTrack.GetSocketName()),
					decodeStr,
				)
				if pipeline != nil {
					err := pipeline.SetState(gst.StateNull)
					if err != nil {
						panic(err)
					}
				}
				pipeline, err = gst.NewPipelineFromString(pipelineStr)
				if err != nil {
					panic(err)
				}
				err = pipeline.Start()
				if err != nil {
					log.Printf("Error starting pipeline: %v", err)
				}
			}
		}
	}
}

func RemoveContents(dir string) error {
	d, err := os.Open(dir)
	if err != nil {
		return err
	}
	defer func(d *os.File) {
		err := d.Close()
		if err != nil {
			panic(err)
		}
	}(d)
	names, err := d.Readdirnames(-1)
	if err != nil {
		return err
	}
	for _, name := range names {
		err = os.RemoveAll(filepath.Join(dir, name))
		if err != nil {
			return err
		}
	}
	return nil
}

func increaseUlimit() {
	var rLimit syscall.Rlimit
	err := syscall.Getrlimit(syscall.RLIMIT_NOFILE, &rLimit)
	if err != nil {
		fmt.Println("Error Getting Rlimit ", err)
	}
	log.Printf("Rlimit Initial: %v", rLimit)
	rLimit.Cur = rLimit.Max
	err = syscall.Setrlimit(syscall.RLIMIT_NOFILE, &rLimit)
	if err != nil {
		log.Println("Error Setting Rlimit ", err)
	}
	err = syscall.Getrlimit(syscall.RLIMIT_NOFILE, &rLimit)
	if err != nil {
		fmt.Println("Error Getting Rlimit ", err)
	}
	log.Println("Rlimit Final", rLimit)
}

func main() {
	log.SetFlags(log.Lshortfile)
	increaseUlimit()
	runtimeDir := os.Getenv("RUNTIME_DIRECTORY")
	if runtimeDir == "" {
		log.Fatal("RUNTIME_DIRECTORY is not set")
	}

	// Clear runtime directory
	err := RemoveContents(runtimeDir)
	if err != nil {
		log.Panicf("Failed to clear runtime directory: %v", err)
	}

	// Remove any existing socket file before starting the server
	udsPath := filepath.Join(runtimeDir, "swarmnode.sock")
	if _, err := os.Stat(udsPath); err == nil {
		if err := os.Remove(udsPath); err != nil {
			log.Panicf("Failed to remove existing socket file: %v", err)
		}
	}
	listener, err := net.Listen("unix", udsPath)
	if err != nil {
		log.Panicf("Failed to listen on UDS: %v", err)
	}
	log.Printf("Serving gRPC on UDS: %s", udsPath)

	// Signal handling for graceful shutdown
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)
	var wg sync.WaitGroup
	serverCtx, stopServer := context.WithCancel(context.Background())
	wg.Add(1)
	go debugTools(runtimeDir, serverCtx, &wg)

	grpcServer := grpc.NewServer([]grpc.ServerOption{
		grpc.Creds(local.NewCredentials()),
		grpc.KeepaliveParams(keepalive.ServerParameters{
			Time:    2 * time.Minute, // Ping the client after 2 minutes of inactivity
			Timeout: 20 * time.Second,
		}),
	}...)
	pb.RegisterWebrtcProxyServer(grpcServer, newWebrtcProxyServer())
	wg.Add(1)
	go func() {
		defer wg.Done()
		if err := grpcServer.Serve(listener); err != nil {
			log.Panicf("Failed to serve gRPC on UDS: %v", err)
		}
	}()

	defer wg.Wait()
	select {
	case <-sigChan:
		log.Println("Received SIGTERM, shutting down")
		stopGracefully := make(chan struct{})
		go func() {
			grpcServer.GracefulStop()
			close(stopGracefully)
		}()

		select {
		case <-stopGracefully:
			log.Println("Graceful shutdown completed")
		case <-time.After(1 * time.Second):
			log.Println("Graceful shutdown timed out, forcing stop")
			grpcServer.Stop()
		}
		stopServer()
		return
	case <-serverCtx.Done():
		log.Println("Server context done, shutting down")
		return
	}
}
