package main

import (
	_ "embed"
	"fmt"
	"github.com/go-gst/go-gst/gst"
	"github.com/pion/webrtc/v4"
	"github.com/stretchr/testify/assert"
	"golang.org/x/exp/maps"
	"google.golang.org/protobuf/proto"
	"log"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
	"webrtc-proxy/grpc/go"
)

var webrtcConfig = WebrtcStateConfig{
	webrtcConfig: webrtc.Configuration{
		ICEServers: []webrtc.ICEServer{
			{
				URLs: []string{"stun:stun.l.google.com:19302"},
			},
		},
	},
	credentials: map[UUID]*pb.WebrtcConfigAuth{
		onionPeerId: pb.WebrtcConfigAuth_builder{
			OnionServiceV3Auth: pb.WebrtcConfigAuth_TorOnionServiceV3_builder{}.Build(),
		}.Build(),
	},
	reconnectAttempts: 0,
	allowedInTracks:   nil,
}

var _port LocalhostPort = 10240
var portMutex sync.Mutex

func getPort() uint32 {
	portMutex.Lock()
	defer portMutex.Unlock()
	_port++
	return _port
}

func buildHTTPServerConfig(addr string) *pb.HttpServer {
	return pb.HttpServer_builder{
		Address: proto.String(addr),
	}.Build()
}

//go:embed testdlhe7gt2jkx4pvaatqhksup6olft3ube6u4huiwrjttgsexsmhyd.onion/hs_ed25519_secret_key
var onionKey []byte

//go:embed testdlhe7gt2jkx4pvaatqhksup6olft3ube6u4huiwrjttgsexsmhyd.onion/hostname
var _onionHostname string
var onionPeerId = "http://" + strings.TrimSpace(_onionHostname) + "/api/webrtc"

func TorServerConfig() *pb.HttpServer {
	return pb.HttpServer_builder{
		Address: proto.String("localhost:0"),
		OnionServiceV3Auth: pb.HttpServer_TorOnionServiceV3_builder{
			HsEd25519SecretKey: onionKey,
			Anonymous:          proto.Bool(true),
		}.Build(),
	}.Build()
}

func TestWebrtcState_OutTrack(t *testing.T) {
	wst, err := NewWebrtcState(webrtcConfig)
	assert.Nil(t, err)
	defer wst.Close()
	assert.Len(t, wst.OutTracks(), 0)

	track1 := NewNamedTrackKey("track1", "stream1", "video/h264")
	track2 := NewNamedTrackKey("track2", "stream2", "video/h264")

	pf := PeeringOffer{
		peerId:      "",
		sdp:         nil,
		outTracks:   map[NamedTrackKey]LocalhostPort{track1: getPort(), track2: getPort()},
		inTracks:    nil,
		dataChannel: true,
	}
	_, err = wst.Peer(pf, 0)
	assert.Nil(t, err)
	assert.Len(t, wst.OutTracks(), 2)
	assert.Contains(t, wst.OutTracks(), track1)
	assert.Contains(t, wst.OutTracks(), track2)
}

func TestWebrtcState_InTrackAllowed(t *testing.T) {
	wst, err := NewWebrtcState(webrtcConfig)
	assert.Nil(t, err)
	defer wst.Close()
	track1 := NewNamedTrackKey("track1", "stream1", "video/h264")
	track2 := NewNamedTrackKey("track2", "stream2", "video/h264")
	track3 := NewNamedTrackKey("track3", "stream3", "video/vp9")
	allowed, _ := wst.InTrackAllowed(track1)
	assert.False(t, allowed)
	allowed, _ = wst.InTrackAllowed(track2)
	assert.False(t, allowed)
	webrtcConfig1 := WebrtcStateConfig{
		webrtcConfig: webrtc.Configuration{
			ICEServers: []webrtc.ICEServer{
				{
					URLs: []string{"stun:stun.l.google.com:19302"},
				},
			},
		},
		reconnectAttempts: 0,
		allowedInTracks:   map[NamedTrackKey]LocalhostPort{track1: getPort(), track2: getPort()},
	}
	wst.Reconfigure(webrtcConfig1)
	allowed, _ = wst.InTrackAllowed(track1)
	assert.True(t, allowed)
	allowed, _ = wst.InTrackAllowed(track2)
	assert.True(t, allowed)
	allowed, _ = wst.InTrackAllowed(track3)
	assert.False(t, allowed)
}

func TestWebrtcState_PutPeer(t *testing.T) {
	wst1, err := NewWebrtcState(webrtcConfig)
	assert.Nil(t, err)
	defer wst1.Close()
	servAddr := "127.0.0.1:8080"
	httpServ := NewWebrtcHttpInterface(wst1, os.TempDir())
	err = httpServ.Configure(buildHTTPServerConfig(servAddr))
	if err != nil {
		panic(err)
	}

	wst2, err := NewWebrtcState(webrtcConfig)
	assert.Nil(t, err)
	defer wst2.Close()
	assert.Len(t, maps.Keys(wst2.peers), 0)
	assert.Len(t, maps.Keys(wst1.peers), 0)
	pf := PeeringOffer{
		peerId:      "http://" + servAddr + "/api/webrtc",
		sdp:         nil,
		outTracks:   nil,
		inTracks:    nil,
		dataChannel: true,
	}
	_, err = wst2.Peer(pf, 0)
	assert.Nil(t, err)
	assert.Len(t, maps.Keys(wst2.peers), 1)
	assert.Len(t, maps.Keys(wst1.peers), 1)
	assert.Contains(t, maps.Keys(wst1.peers), wst2.SrcUUID)
	assert.Contains(t, maps.Keys(wst2.peers), pf.peerId)
	assert.Equal(t, wst1.peers[wst2.SrcUUID].role, WebrtcPeerRoleB)
	assert.Equal(t, wst2.peers[pf.peerId].role, WebrtcPeerRoleT)
	wst2.UnPeer("http://" + servAddr + "/api/webrtc")
	time.Sleep(100 * time.Millisecond)
	assert.Len(t, maps.Keys(wst1.peers), 0)
	pf2 := PeeringOffer{
		peerId:      "http://" + servAddr + "/api/webrtc",
		sdp:         nil,
		outTracks:   nil,
		inTracks:    nil,
		dataChannel: true,
	}
	_, err = wst2.Peer(pf2, 0)
	assert.Nil(t, err)
	assert.Len(t, maps.Keys(wst2.peers), 1)
	assert.Len(t, maps.Keys(wst1.peers), 1)
	assert.Contains(t, maps.Keys(wst1.peers), wst2.SrcUUID)
	assert.Contains(t, maps.Keys(wst2.peers), pf.peerId)
	assert.Equal(t, wst1.peers[wst2.SrcUUID].role, WebrtcPeerRoleB)
	assert.Equal(t, wst2.peers[pf.peerId].role, WebrtcPeerRoleT)
}

func TestWebrtcState_PutPeer_Tor(t *testing.T) {
	LoadTorClient()
	defer DestroyTorClient()
	log.SetFlags(log.Lshortfile)
	wst1, err := NewWebrtcState(webrtcConfig)
	assert.Nil(t, err)
	defer wst1.Close()
	httpServ := NewWebrtcHttpInterface(wst1, os.TempDir())
	defer httpServ.Close()
	err = httpServ.Configure(TorServerConfig())
	if err != nil {
		panic(err)
	}
	log.Println("tor server configured")

	wst2, err := NewWebrtcState(webrtcConfig)
	assert.Nil(t, err)
	defer wst2.Close()
	assert.Len(t, maps.Keys(wst2.peers), 0)
	assert.Len(t, maps.Keys(wst1.peers), 0)
	pf := PeeringOffer{
		peerId:      onionPeerId,
		sdp:         nil,
		outTracks:   nil,
		inTracks:    nil,
		dataChannel: true,
	}
	_, err = wst2.Peer(pf, 0)
	assert.Nil(t, err)
	assert.Len(t, maps.Keys(wst2.peers), 1)
	assert.Len(t, maps.Keys(wst1.peers), 1)
	assert.Contains(t, maps.Keys(wst1.peers), wst2.SrcUUID)
	assert.Contains(t, maps.Keys(wst2.peers), pf.peerId)
	assert.Equal(t, wst1.peers[wst2.SrcUUID].role, WebrtcPeerRoleB)
	assert.Equal(t, wst2.peers[pf.peerId].role, WebrtcPeerRoleT)
	wst2.UnPeer(onionPeerId)
	time.Sleep(5000 * time.Millisecond)
	assert.Len(t, maps.Keys(wst1.peers), 0)
	pf2 := PeeringOffer{
		peerId:      onionPeerId,
		sdp:         nil,
		outTracks:   nil,
		inTracks:    nil,
		dataChannel: true,
	}
	_, err = wst2.Peer(pf2, 0)
	assert.Nil(t, err)
	assert.Len(t, maps.Keys(wst2.peers), 1)
	assert.Len(t, maps.Keys(wst1.peers), 1)
	assert.Contains(t, maps.Keys(wst1.peers), wst2.SrcUUID)
	assert.Contains(t, maps.Keys(wst2.peers), pf.peerId)
	assert.Equal(t, wst1.peers[wst2.SrcUUID].role, WebrtcPeerRoleB)
	assert.Equal(t, wst2.peers[pf.peerId].role, WebrtcPeerRoleT)
}

func TestWebrtcState_PutPeer_DataChannels(t *testing.T) {
	servAddr := "127.0.0.1:8081"
	wst1, err := NewWebrtcState(webrtcConfig)
	assert.Nil(t, err)
	defer wst1.Close()
	httpServ := NewWebrtcHttpInterface(wst1, os.TempDir())
	err = httpServ.Configure(buildHTTPServerConfig(servAddr))
	if err != nil {
		panic(err)
	}

	wst2, err := NewWebrtcState(webrtcConfig)
	assert.Nil(t, err)
	defer wst2.Close()
	pf := PeeringOffer{
		peerId:      "http://" + servAddr + "/api/webrtc",
		sdp:         nil,
		outTracks:   nil,
		inTracks:    nil,
		dataChannel: true,
	}
	_, err = wst2.Peer(pf, 0)
	assert.Nil(t, err)

	trans := pb.DataTransmission{}
	dChan := pb.DataChannel{}
	dChan.SetDestUuid(maps.Keys(wst1.peers)[0])
	trans.SetPayload([]byte("test payload 1wafdf54yrhtfg"))
	trans.SetChannel(&dChan)
	wst1.DataOut <- &trans
	recv := <-wst2.DataIn
	assert.Equal(t, recv.GetPayload(), trans.GetPayload())
	assert.Equal(t, recv.GetChannel().GetSrcUuid(), maps.Keys(wst2.peers)[0])
	assert.False(t, recv.GetChannel().HasDestUuid())
}

func removeGlob(pattern string) {
	// Find files matching the pattern
	files, err := filepath.Glob(pattern)
	if err != nil {
		fmt.Printf("Failed to match files: %v\n", err)
		return
	}

	// Delete each file
	for _, file := range files {
		err := os.Remove(file)
		if err != nil {
			panic(err)
		}
	}
}

func TestWebrtcState_PutPeer_Media(t *testing.T) {
	log.SetFlags(log.Lshortfile)
	servAddr := "127.0.0.1:8082"
	wst1, err := NewWebrtcState(WebrtcStateConfig{
		webrtcConfig: webrtc.Configuration{
			ICEServers: []webrtc.ICEServer{
				{
					URLs: []string{"stun:stun.l.google.com:19302"},
				},
			},
		},
		reconnectAttempts: 0,
		allowedInTracks: map[NamedTrackKey]LocalhostPort{
			NewNamedTrackKey("rgbd", "realsenseD455", "video/h264"): getPort(),
			NewNamedTrackKey("rgbd", "randomSensor", "video/h264"):  getPort(),
		},
	})
	assert.Nil(t, err)
	defer wst1.Close()
	httpServ := NewWebrtcHttpInterface(wst1, os.TempDir())
	err = httpServ.Configure(buildHTTPServerConfig(servAddr))
	if err != nil {
		panic(err)
	}

	wst2, err := NewWebrtcState(webrtcConfig)
	assert.Nil(t, err)
	defer wst2.Close()
	outputTrackKey := NewNamedTrackKey("rgbd", "realsenseD455", "video/h264")
	outPort := getPort()
	pf := PeeringOffer{
		peerId:      "http://" + servAddr + "/api/webrtc",
		sdp:         nil,
		outTracks:   map[NamedTrackKey]LocalhostPort{outputTrackKey: outPort},
		inTracks:    nil,
		dataChannel: false,
	}

	gst.Init(nil)
	pipeline, err := gst.NewPipelineFromString(fmt.Sprintf("videotestsrc is-live=true ! video/x-raw,width=640,height=360,format=I420,framerate=(fraction)30/1 ! x264enc speed-preset=ultrafast tune=zerolatency key-int-max=20 ! rtph264pay ! udpsink host=localhost port=%d name=sink", outPort))
	defer pipeline.SetState(gst.StateNull)
	assert.Nil(t, err)
	assert.Nil(t, pipeline.Start())
	_, err = wst2.Peer(pf, 0)
	assert.Nil(t, err)
	receivedTrack := <-wst1.MediaIn
	assert.Equal(t, receivedTrack.GetTrack().GetTrackId(), outputTrackKey.trackId)
	assert.Equal(t, strings.ToUpper(receivedTrack.GetTrack().GetMimeType()), strings.ToUpper(outputTrackKey.mimeType))
	assert.Equal(t, receivedTrack.GetTrack().GetStreamId(), outputTrackKey.streamId)
	assert.Equal(t, receivedTrack.GetSrcUuid(), wst2.SrcUUID)
}

func TestWebrtcState_Reconcile(t *testing.T) {
	log.SetFlags(log.Lshortfile)
	servAddr := "127.0.0.1:8083"
	wst1, err := NewWebrtcState(WebrtcStateConfig{
		webrtcConfig: webrtc.Configuration{
			ICEServers: []webrtc.ICEServer{
				{
					URLs: []string{"stun:stun.l.google.com:19302"},
				},
			},
		},
		reconnectAttempts: 0,
		allowedInTracks: map[NamedTrackKey]LocalhostPort{
			NewNamedTrackKey("rgbd", "realsenseD455", "video/h264"): getPort(),
			NewNamedTrackKey("rgbd", "randomSensor", "video/h264"):  getPort(),
		},
	})
	assert.Nil(t, err)
	defer wst1.Close()
	httpServ := NewWebrtcHttpInterface(wst1, os.TempDir())
	err = httpServ.Configure(buildHTTPServerConfig(servAddr))
	if err != nil {
		panic(err)
	}

	wst2, err := NewWebrtcState(webrtcConfig)
	assert.Nil(t, err)
	defer wst2.Close()
	outputTrackKey := NewNamedTrackKey("rgbd", "realsenseD455", "video/h264")
	// Create desired state with one peer
	outPort := getPort()
	desiredState := pb.State_builder{
		Data: []*pb.DataChannel{
			pb.DataChannel_builder{DestUuid: proto.String("http://" + servAddr + "/api/webrtc")}.Build(),
		},
		Media: []*pb.MediaChannel{
			pb.MediaChannel_builder{
				DestUuid:      proto.String("http://" + servAddr + "/api/webrtc"),
				Track:         outputTrackKey.toProto(),
				LocalhostPort: proto.Uint32(outPort),
			}.Build(),
		},
	}.Build()
	gst.Init(nil)
	pipeline, err := gst.NewPipelineFromString(fmt.Sprintf("videotestsrc is-live=true ! video/x-raw,width=640,height=360,format=I420,framerate=(fraction)30/1 ! x264enc speed-preset=ultrafast tune=zerolatency key-int-max=20 ! rtph264pay ! udpsink host=localhost port=%d name=sink", outPort))
	assert.Nil(t, err)
	defer pipeline.SetState(gst.StateNull)
	assert.Nil(t, pipeline.Start())

	// Reconcile and verify peer creation
	err = wst2.Reconcile(desiredState)
	assert.Nil(t, err)
	wst2.peersMu.RLock()
	assert.Len(t, wst2.peers, 1, "Should create 1 peer")
	wst2.peersMu.RUnlock()
	receivedTrack := <-wst1.MediaIn
	assert.Equal(t, receivedTrack.GetTrack().GetTrackId(), outputTrackKey.trackId)
	assert.Equal(t, strings.ToUpper(receivedTrack.GetTrack().GetMimeType()), strings.ToUpper(outputTrackKey.mimeType))
	assert.Equal(t, receivedTrack.GetTrack().GetStreamId(), outputTrackKey.streamId)
	assert.Equal(t, receivedTrack.GetSrcUuid(), wst2.SrcUUID)

	// Update desired state to remove peer media
	desiredState.SetMedia(nil)
	err = wst2.Reconcile(desiredState)
	assert.Nil(t, err)
	wst2.peersMu.RLock()
	assert.Len(t, wst2.peers, 1, "Should modify peer")
	assert.Empty(t, maps.Values(wst2.peers)[0].outTracks)
	wst2.peersMu.RUnlock()

	desiredState.SetData(nil)
	err = wst2.Reconcile(desiredState)
	assert.Nil(t, err)
	wst2.peersMu.RLock()
	assert.Empty(t, wst2.peers, "Should modify peer")
	wst2.peersMu.RUnlock()
}
