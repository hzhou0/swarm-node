package main

import (
	"github.com/stretchr/testify/assert"
	"golang.org/x/exp/maps"
	"networking/ipc"
	"runtime"
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
	assert.Nil(t, wst.PutPeer(*pf))
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
	assert.Nil(t, wst.PutPeer(*pf))
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
	wst.SetAllowedInTracks <- []NamedTrackKey{track1, track2}
	time.Sleep(1 * time.Millisecond)
	assert.True(t, wst.InTrackAllowed(track1))
	assert.True(t, wst.InTrackAllowed(track2))
	assert.False(t, wst.InTrackAllowed(track3))
}

func TestWebrtcState_PutPeer(t *testing.T) {
	wst1 := NewWebrtcState()
	servAddr := "127.0.0.1:8080"
	go httpServer(wst1, servAddr)
	wst2 := NewWebrtcState()
	assert.Len(t, maps.Keys(wst2.peers), 0)
	assert.Len(t, maps.Keys(wst1.peers), 0)
	pf := NewPeeringOffer("http://"+servAddr+"/api/webrtc", nil, nil, nil)
	assert.Nil(t, wst2.PutPeer(*pf))
	assert.Len(t, maps.Keys(wst2.peers), 1)
	assert.Len(t, maps.Keys(wst1.peers), 1)
	assert.Contains(t, maps.Keys(wst1.peers), wst2.SrcUUID)
	assert.Contains(t, maps.Keys(wst2.peers), pf.peerId)
	assert.Equal(t, wst1.peers[wst2.SrcUUID].role, WebrtcPeerRoleB)
	assert.Equal(t, wst2.peers[pf.peerId].role, WebrtcPeerRoleT)
	pf2 := NewPeeringOffer("http://"+servAddr+"/api/webrtc", nil, nil, nil)
	assert.Nil(t, wst2.PutPeer(*pf2))
	assert.Len(t, maps.Keys(wst2.peers), 1)
	assert.Len(t, maps.Keys(wst1.peers), 1)
	assert.Contains(t, maps.Keys(wst1.peers), wst2.SrcUUID)
	assert.Contains(t, maps.Keys(wst2.peers), pf.peerId)
	assert.Equal(t, wst1.peers[wst2.SrcUUID].role, WebrtcPeerRoleB)
	assert.Equal(t, wst2.peers[pf.peerId].role, WebrtcPeerRoleT)
}

func TestWebrtcState_PutPeer_DataChannels(t *testing.T) {
	wst1 := NewWebrtcState()
	servAddr := "127.0.0.1:8081"
	go httpServer(wst1, servAddr)
	wst2 := NewWebrtcState()
	pf := NewPeeringOffer("http://"+servAddr+"/api/webrtc", nil, nil, nil)
	assert.Nil(t, wst2.PutPeer(*pf))
	trans1 := ipc.DataTransmission{}
	trans1.SetPayload([]byte("test payload"))
	trans1.SetDestUuid(maps.Keys(wst1.peers)[0])
	wst1.DataOut <- &trans1
	recv1 := <-wst2.DataIn
	assert.Equal(t, recv1.GetPayload(), trans1.GetPayload())
	assert.Equal(t, recv1.GetSrcUuid(), maps.Keys(wst2.peers)[0])
	assert.False(t, recv1.HasDestUuid())
}
