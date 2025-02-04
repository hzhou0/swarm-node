package main

import (
	"github.com/stretchr/testify/assert"
	"github.com/vmihailenco/msgpack/v5"
	"google.golang.org/protobuf/proto"
	"log"
	"networking/ipc"
	"os"
	"testing"
	"time"
)

func setup() (chan *ipc.DataTransmission, chan *ipc.DataTransmission, chan *ipc.MediaChannel, chan *ipc.State) {
	log.SetFlags(log.Lshortfile)
	err := os.Setenv("SWARM_NODE_KERNEL", "test")
	if err != nil {
		panic(err)
	}
	err = os.Setenv("SWARM_NODE_KERNEL_DIR", "/home/henry/Desktop/swarm-node/server/kernels")
	if err != nil {
		panic(err)
	}
	err = os.Setenv("SWARM_NODE_KERNEL_VENV", "/home/henry/Desktop/swarm-node/server/networking/test_kernel/.venv")
	if err != nil {
		panic(err)
	}
	err = os.Setenv("LOG_LEVEL", "INFO")
	if err != nil {
		panic(err)
	}
	DataOut := make(chan *ipc.DataTransmission, 100)
	DataIn := make(chan *ipc.DataTransmission, 100)
	MediaIn := make(chan *ipc.MediaChannel, 100)
	achievedState := make(chan *ipc.State)
	return DataOut, DataIn, MediaIn, achievedState
}

func Test_NewKernel(t *testing.T) {
	DataOut, DataIn, MediaIn, achievedState := setup()
	kernel, err := NewKernel(DataOut, DataIn, MediaIn, achievedState, true)
	if assert.Nil(t, err) {
		time.Sleep(time.Second)
		assert.Nil(t, kernel.cmdCtx.Err())
	}
	kernel.Close()
}

func Test_KernelDataSendRecv(t *testing.T) {
	DataOut, DataIn, MediaIn, achievedState := setup()
	kernel, err := NewKernel(DataOut, DataIn, MediaIn, achievedState, true)
	if assert.Nil(t, err) {
		time.Sleep(time.Second)
		assert.Nil(t, kernel.cmdCtx.Err())
	}
	trans := ipc.DataTransmission{}
	dChan := ipc.DataChannel{}
	dChan.SetSrcUuid("testSrcasdas2347d89d79")
	payload, err := msgpack.Marshal([]byte("test payload 1wafdf54yrhtfg"))
	if err != nil {
		panic(err)
	}
	trans.SetPayload(payload)
	trans.SetChannel(&dChan)
	DataIn <- &trans
	echoTrans := <-DataOut
	assert.Equal(t, trans.GetChannel().GetSrcUuid(), echoTrans.GetChannel().GetDestUuid())
	assert.False(t, trans.GetChannel().HasDestUuid())
	assert.False(t, echoTrans.GetChannel().HasSrcUuid())
	assert.Equal(t, trans.GetPayload(), echoTrans.GetPayload())
	defer kernel.Close()
}

func Test_KernelDataSendRecvLoadTest(t *testing.T) {
	DataOut, DataIn, MediaIn, achievedState := setup()
	kernel, err := NewKernel(DataOut, DataIn, MediaIn, achievedState, true)
	if assert.Nil(t, err) {
		time.Sleep(time.Second)
		assert.Nil(t, kernel.cmdCtx.Err())
	}
	trans := ipc.DataTransmission{}
	dChan := ipc.DataChannel{}
	dChan.SetSrcUuid("testSrcasdas2347d89d79")
	dChan.SetSrcUuid("testSrcasdas2347d89d79")
	payload, err := msgpack.Marshal([]byte("test payload 1wafdf54yrhtfg"))
	if err != nil {
		panic(err)
	}
	trans.SetPayload(payload)
	trans.SetChannel(&dChan)
	encoded, err := proto.Marshal(&trans)
	start := time.Now()
	j := 0
	for i := 0; i < 100000; i++ {
		select {
		case DataIn <- &trans:
			j++
		case <-DataOut:
		}
	}
	for len(DataOut) != 0 {
		<-DataOut
	}
	diff := time.Now().Sub(start)
	log.Printf("%f bytes/second \n", float64(j*len(encoded))/diff.Seconds())
	defer kernel.Close()
}

//func Test_KernelMediaSendRecv(t *testing.T) {
//	DataOut, DataIn, MediaIn, achievedState := setup()
//	kernel, err := NewKernel(DataOut, DataIn, MediaIn, achievedState)
//	if assert.Nil(t, err) {
//		time.Sleep(time.Second)
//		assert.Nil(t, kernel.cmdCtx.Err())
//	}
//
//	// Send a MediaChannel event
//	media := ipc.MediaChannel_builder{
//		SrcUuid: proto.String("testMediaSrc"),
//		Track: ipc.NamedTrack_builder{
//			TrackId:  proto.String("track1"),
//			StreamId: proto.String("stream1"),
//			MimeType: proto.String("video/webm"),
//		}.Build(),
//	}.Build()
//	MediaIn <- media
//
//	// Check the State mutation response
//	select {
//	case state := <-kernel.TargetState:
//		assert.Equal(t, 1, len(state.GetMedia()))
//		mediaResp := state.GetMedia()[0]
//		assert.Equal(t, "testMediaSrc", mediaResp.GetDestUuid())
//		assert.Equal(t, "track1", mediaResp.GetTrack().GetTrackId())
//	case <-time.After(5 * time.Second):
//		t.Fatal("Timeout waiting for media state mutation")
//	}
//
//	defer kernel.Close()
//}

func Test_KernelStateSendRecv(t *testing.T) {
	DataOut, DataIn, MediaIn, achievedState := setup()
	kernel, err := NewKernel(DataOut, DataIn, MediaIn, achievedState, true)
	if assert.Nil(t, err) {
		time.Sleep(time.Second)
		assert.Nil(t, kernel.cmdCtx.Err())
	}

	// Send a State via achievedState
	state := ipc.State_builder{
		ReconnectAttempts: proto.Uint32(5),
		HttpAddr:          proto.String(":8080"),
	}.Build()
	achievedState <- state

	// Check the modified State mutation
	select {
	case modifiedState := <-kernel.TargetState:
		assert.Equal(t, uint32(6), modifiedState.GetReconnectAttempts(), "Reconnect counter increment failed")
		assert.Equal(t, ":8080", modifiedState.GetHttpAddr(), "State preservation failed")
	case <-time.After(5 * time.Second):
		t.Fatal("Timeout waiting for state mutation")
	}

	defer kernel.Close()
}
