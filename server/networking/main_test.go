package main

import (
	"fmt"
	"github.com/go-gst/go-gst/gst"
	"github.com/stretchr/testify/assert"
	"golang.org/x/exp/maps"
	"log"
	"networking/ipc"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

func TestNewWebrtcState(t *testing.T) {
	baseNum := runtime.NumGoroutine()
	wst := NewWebrtcState()
	assert.Equal(t, runtime.NumGoroutine(), baseNum+1)
	wst.Close()
	time.Sleep(1 * time.Millisecond)
	assert.Equal(t, runtime.NumGoroutine(), baseNum)
}

func TestWebrtcState_OutTrack(t *testing.T) {
	wst := NewWebrtcState()
	assert.Len(t, wst.OutTracks(), 0)
	track1 := NewNamedTrackKey("", "track1", "stream1", "video/h264")
	track2 := NewNamedTrackKey("", "track2", "stream2", "video/h264")
	pf := NewPeeringOffer("", nil, []NamedTrackKey{track1, track2}, nil)
	err, _ := wst.Peer(*pf)
	assert.Nil(t, err)
	assert.Len(t, wst.OutTracks(), 2)
	assert.Contains(t, wst.OutTracks(), track1)
	assert.Contains(t, wst.OutTracks(), track2)
}

func TestWebrtcState_OutTrackAllowed(t *testing.T) {
	wst := NewWebrtcState()
	track1 := NewNamedTrackKey("", "track1", "stream1", "video/h264")
	track2 := NewNamedTrackKey("", "track2", "stream2", "video/h264")
	track3 := NewNamedTrackKey("", "track3", "stream3", "video/vp9")
	pf := NewPeeringOffer("", nil, []NamedTrackKey{track1, track2}, nil)
	err, _ := wst.Peer(*pf)
	assert.Nil(t, err)
	assert.True(t, wst.OutTrackAllowed(track1))
	assert.True(t, wst.OutTrackAllowed(track2))
	assert.False(t, wst.OutTrackAllowed(track3))
}

func TestWebrtcState_InTrackAllowed(t *testing.T) {
	wst := NewWebrtcState()
	track1 := NewNamedTrackKey("", "track1", "stream1", "video/h264")
	track2 := NewNamedTrackKey("", "track2", "stream2", "video/h264")
	track3 := NewNamedTrackKey("", "track3", "stream3", "video/vp9")
	assert.False(t, wst.InTrackAllowed(track1))
	assert.False(t, wst.InTrackAllowed(track2))
	wst.SetAllowedInTracks([]NamedTrackKey{track1, track2})
	assert.True(t, wst.InTrackAllowed(track1))
	assert.True(t, wst.InTrackAllowed(track2))
	assert.False(t, wst.InTrackAllowed(track3))
}

func TestWebrtcState_PutPeer(t *testing.T) {
	wst1 := NewWebrtcState()
	servAddr := "127.0.0.1:8080"
	runHttpServer(wst1, servAddr)
	wst2 := NewWebrtcState()
	assert.Len(t, maps.Keys(wst2.peers), 0)
	assert.Len(t, maps.Keys(wst1.peers), 0)
	pf := NewPeeringOffer("http://"+servAddr+"/api/webrtc", nil, nil, nil)
	err, _ := wst2.Peer(*pf)
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
	pf2 := NewPeeringOffer("http://"+servAddr+"/api/webrtc", nil, nil, nil)
	err, _ = wst2.Peer(*pf2)
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
	wst1 := NewWebrtcState()
	runHttpServer(wst1, servAddr)
	wst2 := NewWebrtcState()
	pf := NewPeeringOffer("http://"+servAddr+"/api/webrtc", nil, nil, nil)
	err, _ := wst2.Peer(*pf)
	assert.Nil(t, err)

	trans := ipc.DataTransmission{}
	trans.SetPayload([]byte("test payload 1wafdf54yrhtfg"))
	trans.SetDestUuid(maps.Keys(wst1.peers)[0])
	wst1.DataOut <- &trans

	recv := <-wst2.DataIn

	assert.Equal(t, recv.GetPayload(), trans.GetPayload())
	assert.Equal(t, recv.GetSrcUuid(), maps.Keys(wst2.peers)[0])
	assert.False(t, recv.HasDestUuid())
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
	removeGlob("/dev/shm/shmpipe.*")
	err := os.RemoveAll("/tmp/swarmnode-network")
	if err != nil {
		panic(err)
	}

	log.SetFlags(log.Lshortfile)
	servAddr := "127.0.0.1:8082"
	wst1 := NewWebrtcState()
	wst1.SetAllowedInTracks([]NamedTrackKey{
		NewNamedTrackKey("", "rgbd", "realsenseD455", "video/h264"),
		NewNamedTrackKey("", "rgbd", "randomSensor", "video/h264"),
	})
	runHttpServer(wst1, servAddr)
	wst2 := NewWebrtcState()
	outputTrackKey := NewNamedTrackKey("", "rgbd", "realsenseD455", "video/h264")
	pf := NewPeeringOffer("http://"+servAddr+"/api/webrtc", nil, []NamedTrackKey{outputTrackKey}, nil)

	gst.Init(nil)
	pipeline, err := gst.NewPipelineFromString(fmt.Sprintf("videotestsrc is-live=true ! video/x-raw,width=640,height=360,format=I420,framerate=(fraction)30/1 ! x264enc speed-preset=ultrafast tune=zerolatency key-int-max=20 ! shmsink wait-for-connection=true socket-path=%s name=sink", outputTrackKey.shmPath))
	assert.Nil(t, err)
	assert.Nil(t, pipeline.Start())
	err, _ = wst2.Peer(*pf)
	assert.Nil(t, err)
	receivedTrack := <-wst1.InTrack
	assert.Equal(t, receivedTrack.trackId, outputTrackKey.trackId)
	assert.Equal(t, strings.ToUpper(receivedTrack.mimeType), strings.ToUpper(outputTrackKey.mimeType))
	assert.Equal(t, receivedTrack.streamId, outputTrackKey.streamId)
	assert.Equal(t, receivedTrack.sender, wst2.SrcUUID)
	assert.FileExists(t, receivedTrack.shmPath)
}
