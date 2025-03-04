//go:build linux

package main

import (
	"context"
	"fmt"
	"github.com/go-gst/go-gst/gst"
	"github.com/pion/webrtc/v4"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/local"
	"google.golang.org/grpc/keepalive"
	"google.golang.org/protobuf/proto"
	"io"
	"log"
	"net"
	"os"
	"os/signal"
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
		reconnectAttempts: 0,
		allowedInTracks:   nil,
	}
	return &webrtcProxyServer{defaultConfig: webrtcConfig}
}

func (s *webrtcProxyServer) Connect(stream pb.WebrtcProxy_ConnectServer) error {
	runtimeDir := os.Getenv("RUNTIME_DIRECTORY")
	if runtimeDir == "" {
		return fmt.Errorf("RUNTIME_DIRECTORY is not set")
	}
	webrtcState, err := NewWebrtcState(s.defaultConfig)
	if err != nil {
		return err
	}
	defer webrtcState.Close()

	setState := make(chan *pb.State)
	achievedState := make(chan *pb.State)

	errChan := make(chan error)
	httpServer := NewWebrtcHttpInterface(webrtcState, runtimeDir)
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
		lastAchievedState := pb.State_builder{}.Build()
		for {
			ev := pb.Event{}
			select {
			case data := <-webrtcState.DataIn:
				ev.SetData(data)
			case media := <-webrtcState.MediaIn:
				ev.SetMedia(media)
			case state := <-achievedState:
				if proto.Equal(state, lastAchievedState) {
					continue
				} else {
					lastAchievedState = state
					ev.SetAchievedState(state)
				}
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
		case err := <-httpServer.Error:
			log.Println(err)
			stateMsg, err := webrtcState.ToProto(httpServer)
			if err != nil {
				log.Printf("Error converting state to proto: %v", err)
				return err
			}
			achievedState <- stateMsg
		}
	}
}

func debugTools(ctx context.Context, wg *sync.WaitGroup) {
	defer wg.Done()
	debugSendVideo := os.Getenv("DEBUG_SEND_VIDEO")
	if debugSendVideo != "" {
		var port uint32 = 16400
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
			allowedInTracks:   nil,
		}

		debugState, err := NewWebrtcState(config)
		if err != nil {
			panic(err)
		}
		defer debugState.Close()

		outputTrackKey := NewNamedTrackKey("rgbd", "realsenseD455", debugSendVideo)
		pf := PeeringOffer{
			peerId:      "http://localhost:8080/api/webrtc",
			sdp:         nil,
			outTracks:   map[NamedTrackKey]LocalhostPort{outputTrackKey: port},
			inTracks:    nil,
			dataChannel: false,
		}
		pipelineStr := fmt.Sprintf(
			"videotestsrc is-live=true pattern=smpte ! video/x-raw,width=1280,height=720,format=I420,framerate=(fraction)30/1 ! %s ! udpsink host=localhost port=%d",
			encodeStr,
			port,
		)
		pipeline, err := gst.NewPipelineFromString(pipelineStr)
		pipeline.GetBus().AddWatch(func(msg *gst.Message) bool {
			switch msg.Type() {
			case gst.MessageEOS:
				fallthrough
			case gst.MessageError:
				gErr := msg.ParseError()
				log.Printf("Pipeline error (%v): %s, Debug info: %s\n", gErr.Code(), gErr.Message(), gErr.DebugString())
				err := pipeline.SetState(gst.StateNull)
				if err != nil {
					log.Printf("Error stopping pipeline: %v", err)
				}
				return false
			}
			return true
		})

		if err != nil {
			panic(err)
		}
		err = pipeline.BlockSetState(gst.StatePlaying)
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
		var port uint32 = 16401
		config := WebrtcStateConfig{
			webrtcConfig: webrtc.Configuration{
				ICEServers: []webrtc.ICEServer{
					{
						URLs: []string{"stun:stun.l.google.com:19302"},
					},
				},
			},
			reconnectAttempts: 0,
			allowedInTracks: map[NamedTrackKey]LocalhostPort{
				NewNamedTrackKey("rgbd", "realsenseD455", "video/h265"): port,
			},
		}

		debugState, err := NewWebrtcState(config)
		if err != nil {
			panic(err)
		}
		defer debugState.Close()
		temp, err := os.MkdirTemp(os.TempDir(), "swarmnode-debug-recv-*")
		if err != nil {
			panic(err)
		}
		defer os.RemoveAll(temp)
		httpServ := NewWebrtcHttpInterface(debugState, temp)
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
					decodeStr = "rtph264depay ! avdec_h264"
				case "video/h265":
					decodeStr = "rtph265depay ! avdec_h265"
				default:
					log.Printf("Unknown debug video type: %s\n", debugSendVideo)
					return
				}
				pipelineStr := fmt.Sprintf(
					"udpsrc address=localhost port=%d ! application/x-rtp ! %s ! autovideosink sync=false",
					port,
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

// MaximizeNOFILELimit attempts to maximize the current process's NOFILE limit to its maximum allowable value.
// WebRTC can create a lot of sockets for media, do this on startup to prevent going over soft limit.
func MaximizeNOFILELimit() {
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
	MaximizeNOFILELimit()
	runtimeDir := os.Getenv("RUNTIME_DIRECTORY")
	if runtimeDir == "" {
		log.Fatal("RUNTIME_DIRECTORY is not set")
	}
	//LoadTorClient()
	defer DestroyTorClient()

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
	go debugTools(serverCtx, &wg)

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
