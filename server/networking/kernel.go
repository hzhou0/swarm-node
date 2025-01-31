package main

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"google.golang.org/protobuf/proto"
	"io"
	"log"
	"networking/ipc"
	"os"
	"os/exec"
	"path"
	"time"
)

type KernelLogWriter struct {
	output       io.Writer
	kernelEnvVar string
}

func (k KernelLogWriter) Write(p []byte) (n int, err error) {
	return k.output.Write([]byte(fmt.Sprintf("[%s] %s", k.kernelEnvVar, string(p))))
}

type Kernel struct {
	envVar     string
	venvPath   string
	entrypoint string
	eventW     *os.File
	mutationR  *os.File
	cmd        *exec.Cmd
	Close      context.CancelFunc
	Ctx        context.Context

	dataOut     chan<- *ipc.DataTransmission
	dataIn      <-chan *ipc.DataTransmission
	inTrack     <-chan NamedTrackKey
	targetState chan *ipc.State
}

func NewKernel(dataOut chan<- *ipc.DataTransmission, dataIn <-chan *ipc.DataTransmission, inTrack <-chan NamedTrackKey) (Kernel, error) {
	k := Kernel{
		dataOut:     dataOut,
		dataIn:      dataIn,
		inTrack:     inTrack,
		targetState: make(chan *ipc.State),
	}

	k.envVar = os.Getenv("SWARM_NODE_KERNEL")
	if k.envVar == "" {
		return k, errors.New("env var SWARM_NODE_KERNEL not set")
	}
	switch k.envVar {
	case "test":
		k.entrypoint = "networking/python_sdk/test_kernel.py"
	case "december":
		k.entrypoint = "kernels/december/main.py"
	case "skymap-sens-arr":
		k.entrypoint = "kernels/skymap/sensor_array/main.py"
	case "skymap-serv":
		k.entrypoint = "kernels/skymap/server/main.py"
	default:
		return k, errors.New(fmt.Sprintf("Unknown kernel %s,exiting", k.envVar))
	}

	k.venvPath = os.Getenv("SWARM_NODE_KERNEL_VENV")
	if k.venvPath == "" {
		return k, errors.New("env var SWARM_NODE_KERNEL_VENV not set")
	}

	activateScript := path.Join(k.venvPath, "bin", "activate")
	cmd := exec.Command("bash", "-c", activateScript+" && env")
	envOutput, err := cmd.CombinedOutput()
	if err != nil {
		log.Fatal(err)
	}
	sourcedEnvBytes := bytes.Split(envOutput, []byte("\n"))
	var sourcedEnv []string
	for i, b := range sourcedEnvBytes {
		sourcedEnv[i] = string(b)
	}

	eventR, eventW, err := os.Pipe()
	if err != nil {
		return k, err
	}
	mutationR, mutationW, err := os.Pipe()
	if err != nil {
		return k, err
	}
	k.eventW = eventW
	k.mutationR = mutationR

	k.Ctx, k.Close = context.WithCancel(context.Background())
	k.cmd = exec.CommandContext(k.Ctx, "python3", k.entrypoint)
	k.cmd.WaitDelay = 5 * time.Second
	k.cmd.Env = append(sourcedEnv, "SWARM_NODE_KERNEL="+k.envVar)
	k.cmd.Stderr = KernelLogWriter{output: os.Stderr, kernelEnvVar: k.envVar}
	k.cmd.Stdout = KernelLogWriter{output: os.Stdout, kernelEnvVar: k.envVar}
	k.cmd.ExtraFiles = []*os.File{eventR, mutationW}
	k.cmd.Cancel = func() error {
		err := k.cmd.Process.Signal(os.Interrupt)
		if err != nil {
			err := k.cmd.Process.Kill()
			if err != nil {
				panic(err)
			}
		} else {
			done := make(chan struct{})
			go func() {
				err := k.cmd.Wait()
				if err != nil {
					return
				}
				close(done)
			}()
			select {
			case <-time.After(1 * time.Second):
				log.Println("Force killing kernel.")
				err := k.cmd.Process.Kill()
				if err != nil {
					panic(err)
				}
			case <-done:
				log.Println("Python kernel gracefully destroyed.")
			}
		}
		_ = k.eventW.Close()
		_ = k.mutationR.Close()
		return os.ErrProcessDone
	}

	err = k.cmd.Start()
	if err != nil {
		k.Close()
		return k, err
	}

	go func() {
		err := k.cmd.Wait()
		if k.Ctx.Err() == nil {
			log.Printf("Kernel exited on its own, err: %v\n", err)
			k.Close()
		}
	}()
	go k.streamMutations()
	go k.streamEvents()
	return k, nil
}

func (k *Kernel) streamMutations() {
	for {
		mutations, err := getMutations(k.mutationR)
		if err != nil {
			k.Close()
			return
		}
		for i := 0; i < len(mutations); i++ {
			mutation := &(mutations)[i]
			if mutation.HasData() {
				k.dataOut <- mutation.GetData()
			}
			if mutation.HasSetState() {
				k.targetState <- mutation.GetSetState()
			}
		}
	}
}

func (k *Kernel) streamEvents() {
	for {
		ev := ipc.Event{}
		select {
		case dataIn := <-k.dataIn:
			ev.SetData(dataIn)
		case track := <-k.inTrack:
			m := ipc.MediaChannel{}
			t := ipc.NamedTrack{}
			t.SetStreamId(track.streamId)
			t.SetTrackId(track.trackId)
			t.SetMimeType(track.mimeType)
			m.SetSrcUuid(track.sender)
			m.SetTrack(&t)
			ev.SetMedia(&m)
		}
		err := k.writeEvent(&ev)
		if err != nil {
			k.Close()
			return
		}
	}
}

func (k *Kernel) writeEvent(event *ipc.Event) error {
	encoded, err := proto.Marshal(event)
	if err != nil {
		panic(err)
	}
	encoded = cobsEncoder.Encode(encoded)
	encoded = append([]byte{0}, append(encoded, 0)...)
	err = k.eventW.SetWriteDeadline(time.Now().Add(1 * time.Second))
	if err != nil {
		return err
	}
	_, err = k.eventW.Write(encoded)
	if err != nil {
		return err
	}
	return nil
}

var eventBuf = make([]byte, 65536)

func getMutations(eventR *os.File) (event []ipc.Mutation, err error) {
	err = eventR.SetReadDeadline(time.Now().Add(1 * time.Second))
	if err != nil {
		return nil, err
	}
	n := 0
	for {
		n1, err := eventR.Read(eventBuf[n:])
		if n1 == 0 || err == io.EOF {
			return nil, nil
		} else if err != nil {
			return nil, err
		}
		if n1 == len(eventBuf) {
			eventBuf = append(eventBuf, make([]byte, len(eventBuf))...) //increase the len of eventBuf
		} else {
			break
		}
		n += n1
	}

	begin := -1
	end := -1
	mutations := make([]ipc.Mutation, 5)
	j := 0
	for i := 0; i < n; i++ {
		if eventBuf[i] == 0x00 && begin == -1 {
			begin = i
		}
		if eventBuf[i] == 0x00 && begin != -1 {
			end = i
		}
		if begin != -1 && end != -1 {
			msg := eventBuf[begin+1 : end]
			end = -1
			begin = -1
			err := proto.Unmarshal(msg, &mutations[j])
			if err != nil {
				continue
			}
			j++
			if j >= cap(mutations) {
				newKernelEvents := make([]ipc.Mutation, j*2)
				copy(newKernelEvents, mutations)
				mutations = newKernelEvents
			}
		}
	}
	return mutations, nil
}
