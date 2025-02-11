package main

import (
	"fmt"
	"github.com/go-gst/go-gst/gst"
	"github.com/pion/webrtc/v4"
	"github.com/stretchr/testify/assert"
	"golang.org/x/exp/maps"
	"google.golang.org/protobuf/proto"
	"log"
	"os"
	"path/filepath"
	"runtime"
	"strings"
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
	reconnectAttempts: 0,
	allowedInTracks:   []NamedTrackKey{},
}

func generateSocketDirs() (string, string, string, string) {
	return "/tmp/swarmnode/client" + NewUUID(), "/tmp/swarmnode/server" + NewUUID(), "/tmp/swarmnode/client2" + NewUUID(), "/tmp/swarmnode/server2" + NewUUID()
}

func TestNewWebrtcState(t *testing.T) {
	serverSocketDir, clientSocketDir, _, _ := generateSocketDirs()
	baseNum := runtime.NumGoroutine()
	wst, err := NewWebrtcState(webrtcConfig, serverSocketDir, clientSocketDir)
	assert.Nil(t, err)
	assert.Equal(t, runtime.NumGoroutine(), baseNum+1)
	wst.Close()
	time.Sleep(1 * time.Millisecond)
	assert.Equal(t, runtime.NumGoroutine(), baseNum)
}

func TestWebrtcState_OutTrack(t *testing.T) {
	serverSocketDir, clientSocketDir, _, _ := generateSocketDirs()
	wst, err := NewWebrtcState(webrtcConfig, serverSocketDir, clientSocketDir)
	assert.Nil(t, err)
	defer wst.Close()
	assert.Len(t, wst.OutTracks(), 0)

	track1 := NewNamedTrackKey("track1", "stream1", "video/h264")
	track2 := NewNamedTrackKey("track2", "stream2", "video/h264")

	pf := PeeringOffer{
		peerId:      "",
		sdp:         nil,
		outTracks:   []NamedTrackKey{track1, track2},
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
	serverSocketDir, clientSocketDir, _, _ := generateSocketDirs()
	wst, err := NewWebrtcState(webrtcConfig, serverSocketDir, clientSocketDir)
	assert.Nil(t, err)
	defer wst.Close()
	track1 := NewNamedTrackKey("track1", "stream1", "video/h264")
	track2 := NewNamedTrackKey("track2", "stream2", "video/h264")
	track3 := NewNamedTrackKey("track3", "stream3", "video/vp9")
	assert.False(t, wst.InTrackAllowed(track1))
	assert.False(t, wst.InTrackAllowed(track2))
	webrtcConfig1 := WebrtcStateConfig{
		webrtcConfig: webrtc.Configuration{
			ICEServers: []webrtc.ICEServer{
				{
					URLs: []string{"stun:stun.l.google.com:19302"},
				},
			},
		},
		reconnectAttempts: 0,
		allowedInTracks:   []NamedTrackKey{track1, track2},
	}
	wst.Reconfigure(webrtcConfig1)
	assert.True(t, wst.InTrackAllowed(track1))
	assert.True(t, wst.InTrackAllowed(track2))
	assert.False(t, wst.InTrackAllowed(track3))
}

func TestWebrtcState_PutPeer(t *testing.T) {
	serverSocketDir, clientSocketDir, serverSocketDir2, clientSocketDir2 := generateSocketDirs()
	wst1, err := NewWebrtcState(webrtcConfig, serverSocketDir, clientSocketDir)
	assert.Nil(t, err)
	defer wst1.Close()
	servAddr := "127.0.0.1:8080"
	httpServ := NewWebrtcHttpServer(wst1)
	httpServ.SetAddr(servAddr)

	wst2, err := NewWebrtcState(webrtcConfig, serverSocketDir2, clientSocketDir2)
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
	time.Sleep(200 * time.Millisecond)
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

func TestWebrtcState_PutPeer_DataChannels(t *testing.T) {
	serverSocketDir, clientSocketDir, serverSocketDir2, clientSocketDir2 := generateSocketDirs()
	servAddr := "127.0.0.1:8081"
	wst1, err := NewWebrtcState(webrtcConfig, serverSocketDir, clientSocketDir)
	assert.Nil(t, err)
	defer wst1.Close()
	httpServ := NewWebrtcHttpServer(wst1)
	httpServ.SetAddr(servAddr)

	wst2, err := NewWebrtcState(webrtcConfig, serverSocketDir2, clientSocketDir2)
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
	serverSocketDir, clientSocketDir, serverSocketDir2, clientSocketDir2 := generateSocketDirs()

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
		allowedInTracks: []NamedTrackKey{
			NewNamedTrackKey("rgbd", "realsenseD455", "video/h264"),
			NewNamedTrackKey("rgbd", "randomSensor", "video/h264"),
		},
	}, serverSocketDir, clientSocketDir)
	assert.Nil(t, err)
	defer wst1.Close()
	httpServ := NewWebrtcHttpServer(wst1)
	httpServ.SetAddr(servAddr)

	wst2, err := NewWebrtcState(webrtcConfig, serverSocketDir2, clientSocketDir2)
	assert.Nil(t, err)
	defer wst2.Close()
	outputTrackKey := NewNamedTrackKey("rgbd", "realsenseD455", "video/h264")
	pf := PeeringOffer{
		peerId:      "http://" + servAddr + "/api/webrtc",
		sdp:         nil,
		outTracks:   []NamedTrackKey{outputTrackKey},
		inTracks:    nil,
		dataChannel: false,
	}

	gst.Init(nil)
	pipeline, err := gst.NewPipelineFromString(fmt.Sprintf("videotestsrc is-live=true ! video/x-raw,width=640,height=360,format=I420,framerate=(fraction)30/1 ! x264enc speed-preset=ultrafast tune=zerolatency key-int-max=20 ! shmsink wait-for-connection=true socket-path=%s name=sink", outputTrackKey.shmPath(clientSocketDir2, "")))
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
	//assert.FileExists(t, NamedTrackKeyFromProto(receivedTrack.GetTrack()).shmPath(serverSocketDir, receivedTrack.GetSrcUuid()))
	select {}
}

func TestWebrtcState_Reconcile(t *testing.T) {
	serverSocketDir, clientSocketDir, serverSocketDir2, clientSocketDir2 := generateSocketDirs()
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
		allowedInTracks: []NamedTrackKey{
			NewNamedTrackKey("rgbd", "realsenseD455", "video/h264"),
			NewNamedTrackKey("rgbd", "randomSensor", "video/h264"),
		},
	}, serverSocketDir, clientSocketDir)
	assert.Nil(t, err)
	defer wst1.Close()
	httpServ := NewWebrtcHttpServer(wst1)
	httpServ.SetAddr(servAddr)

	wst2, err := NewWebrtcState(webrtcConfig, serverSocketDir2, clientSocketDir2)
	assert.Nil(t, err)
	defer wst2.Close()
	outputTrackKey := NewNamedTrackKey("rgbd", "realsenseD455", "video/h264")
	// Create desired state with one peer
	desiredState := pb.State_builder{
		Data: []*pb.DataChannel{
			pb.DataChannel_builder{DestUuid: proto.String("http://" + servAddr + "/api/webrtc")}.Build(),
		},
		Media: []*pb.MediaChannel{
			pb.MediaChannel_builder{
				DestUuid: proto.String("http://" + servAddr + "/api/webrtc"),
				Track:    outputTrackKey.toProto(),
			}.Build(),
		},
	}.Build()
	gst.Init(nil)
	pipeline, err := gst.NewPipelineFromString(fmt.Sprintf("videotestsrc is-live=true ! video/x-raw,width=640,height=360,format=I420,framerate=(fraction)30/1 ! x264enc speed-preset=ultrafast tune=zerolatency key-int-max=20 ! shmsink wait-for-connection=true socket-path=%s name=sink", outputTrackKey.shmPath(clientSocketDir2, "")))
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
	assert.FileExists(t, NamedTrackKeyFromProto(receivedTrack.GetTrack()).shmPath(serverSocketDir, receivedTrack.GetSrcUuid()))

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
