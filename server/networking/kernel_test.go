package main

import (
	"github.com/stretchr/testify/assert"
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
	err = os.Setenv("SWARM_NODE_KERNEL_VENV", "/home/henry/Desktop/swarm-node/server/networking/python_sdk/.venv")
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
	kernel, err := NewKernel(DataOut, DataIn, MediaIn, achievedState)
	if assert.Nil(t, err) {
		time.Sleep(time.Second)
		assert.Nil(t, kernel.cmdCtx.Err())
	}
	kernel.Close()
}

func Test_KernelDataSendRecv(t *testing.T) {
	DataOut, DataIn, MediaIn, achievedState := setup()
	kernel, err := NewKernel(DataOut, DataIn, MediaIn, achievedState)
	if assert.Nil(t, err) {
		time.Sleep(time.Second)
		assert.Nil(t, kernel.cmdCtx.Err())
	}
	trans := ipc.DataTransmission{}
	dChan := ipc.DataChannel{}
	dChan.SetSrcUuid("testSrcasdas2347d89d79")
	trans.SetPayload([]byte("test payload 1wafdf54yrhtfg"))
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
	kernel, err := NewKernel(DataOut, DataIn, MediaIn, achievedState)
	if assert.Nil(t, err) {
		time.Sleep(time.Second)
		assert.Nil(t, kernel.cmdCtx.Err())
	}
	trans := ipc.DataTransmission{}
	dChan := ipc.DataChannel{}
	dChan.SetSrcUuid("testSrcasdas2347d89d79")
	trans.SetPayload([]byte("test payload 1wafdf54yrhtfg"))
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
