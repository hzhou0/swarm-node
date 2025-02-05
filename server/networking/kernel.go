package main

import (
	"context"
	"errors"
	"fmt"
	"golang.org/x/sys/unix"
	"google.golang.org/protobuf/proto"
	"io"
	"log"
	"networking/ipc"
	"os"
	"os/exec"
	"path"
	"syscall"
	"time"
)

type Kernel struct {
	envVar     string
	venvPath   string
	entrypoint string
	eventW     *os.File
	mutationR  *os.File
	cmd        *exec.Cmd
	cmdCancel  context.CancelFunc
	cmdCtx     context.Context
	cmdDone    chan struct{}

	dataOut       chan<- *ipc.DataTransmission
	dataIn        <-chan *ipc.DataTransmission
	mediaIn       <-chan *ipc.MediaChannel
	TargetState   chan *ipc.State
	achievedState <-chan *ipc.State
}

func NewKernel(dataOut chan<- *ipc.DataTransmission, dataIn <-chan *ipc.DataTransmission, mediaIn <-chan *ipc.MediaChannel, achievedState <-chan *ipc.State, panicOnExit bool) (Kernel, error) {
	k := Kernel{
		dataOut:       dataOut,
		dataIn:        dataIn,
		mediaIn:       mediaIn,
		achievedState: achievedState,
		TargetState:   make(chan *ipc.State),
		cmdDone:       make(chan struct{}),
	}
	basePath := os.Getenv("SWARM_NODE_KERNEL_DIR")
	if basePath == "" {
		return k, errors.New("env var SWARM_NODE_KERNEL_DIR not set")
	}
	k.envVar = os.Getenv("SWARM_NODE_KERNEL")
	if k.envVar == "" {
		return k, errors.New("env var SWARM_NODE_KERNEL not set")
	}
	switch k.envVar {
	case "test":
		k.entrypoint = "../networking/test_kernel/test_kernel.py"
	case "december":
		k.entrypoint = "december/main.py"
	case "skymap-sens-arr":
		k.entrypoint = "skymap/sensor_array/main.py"
	case "skymap-serv":
		k.entrypoint = "skymap/server/main.py"
	default:
		return k, errors.New(fmt.Sprintf("Unknown kernel %s,exiting", k.envVar))
	}
	k.entrypoint = path.Join(basePath, k.entrypoint)

	k.venvPath = os.Getenv("SWARM_NODE_KERNEL_VENV")
	if k.venvPath == "" {
		return k, errors.New("env var SWARM_NODE_KERNEL_VENV not set")
	}

	activateScript := path.Join(k.venvPath, "bin", "activate")

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

	k.cmdCtx, k.cmdCancel = context.WithCancel(context.Background())
	k.cmd = exec.CommandContext(k.cmdCtx, "bash", "-c", "source "+activateScript+" && python "+k.entrypoint)
	k.cmd.WaitDelay = 1 * time.Second
	k.cmd.Stderr = os.Stderr
	k.cmd.Stdout = os.Stdout
	k.cmd.Env = append(os.Environ(), []string{"PYTHONUNBUFFERED=1"}...)
	k.cmd.ExtraFiles = []*os.File{eventR, mutationW}
	k.cmd.Cancel = func() error {
		err := k.cmd.Process.Signal(os.Interrupt)
		if err != nil {
			err := k.cmd.Process.Kill()
			if err != nil {
				panic(err)
			}
		}
		return os.ErrProcessDone
	}

	err = k.cmd.Start()
	if err != nil {
		k.cmdCancel()
		return k, err
	}

	go func() {
		err := k.cmd.Wait()
		_ = k.eventW.Close()
		_ = k.mutationR.Close()
		close(k.cmdDone)
		select {
		case <-k.cmdCtx.Done():
			if err == nil {
				log.Printf("Kernel exited gracefully\n")
			} else {
				log.Printf("Kernel killed, err: %v\n", err)
			}
		default:
			log.Printf("Kernel exited on its own, err: %v\n", err)
			k.cmdCancel()
			if panicOnExit {
				panic(err)
			}
		}
	}()
	go k.streamMutations()
	go k.streamEvents()
	return k, nil
}

func (k *Kernel) Close() {
	k.cmdCancel()
	<-k.cmdDone
}

func (k *Kernel) streamMutations() {
	var readFds unix.FdSet
	readFds.Set(int(k.mutationR.Fd()))
	for {
		select {
		case <-k.cmdCtx.Done():
			return
		default:
		}
	selSyscall:
		_, err := unix.Select(int(k.mutationR.Fd()+1), &readFds, nil, nil, &unix.Timeval{Sec: 1})
		if errors.Is(err, syscall.EINTR) {
			goto selSyscall
		} else if err != nil {
			log.Printf("Unix select failed: %s\n", err)
			k.cmdCancel()
			return
		}
		mutations, err := getMutations(k.mutationR)
		if err != nil {
			log.Printf("Getmutations failed: %s\n", err)
			k.cmdCancel()
			return
		}
		for i := 0; i < len(mutations); i++ {
			mutation := mutations[i]
			if mutation.HasData() {
				k.dataOut <- mutation.GetData()
			}
			if mutation.HasSetState() {
				k.TargetState <- mutation.GetSetState()
			}
		}
	}
}

func (k *Kernel) streamEvents() {
	for {
		ev := ipc.Event{}
		select {
		case <-k.cmdCtx.Done():
			return
		case dataIn := <-k.dataIn:
			ev.SetData(dataIn)
		case media := <-k.mediaIn:
			ev.SetMedia(media)
		case state := <-k.achievedState:
			ev.SetAchievedState(state)
		}
		err := k.writeEvent(&ev)
		if err != nil {
			log.Println(err)
			k.cmdCancel()
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
		return fmt.Errorf("eventW set deadline failed %w", err)
	}
	_, err = k.eventW.Write(encoded)
	if err != nil {
		return fmt.Errorf("eventW write failed %w", err)
	}
	return nil
}

var mutationBuf = make([]byte, 65536)

func getMutations(mutationR *os.File) ([]*ipc.Mutation, error) {
	err := mutationR.SetReadDeadline(time.Now().Add(1 * time.Second))
	if err != nil {
		return nil, err
	}
	n := 0
	for {
		n1, err := mutationR.Read(mutationBuf[n:])
		if n1 == 0 || err == io.EOF {
			return nil, nil
		} else if err != nil {
			return nil, err
		}
		n += n1
		if n1 == len(mutationBuf) {
			mutationBuf = append(mutationBuf, make([]byte, len(mutationBuf))...) //increase the len of mutationBuf
		} else {
			break
		}
	}
	if n == 0 {
		return nil, nil
	}

	begin := -1
	end := -1
	mutations := make([]*ipc.Mutation, 0)
	for i := 0; i < n; i++ {
		if mutationBuf[i] == 0x00 {
			if begin == -1 {
				begin = i
			} else {
				end = i
			}
		}
		if begin != -1 && end != -1 {
			if end-begin < 2 {
				begin = end
				end = -1
			} else {
				msg := cobsEncoder.Decode(mutationBuf[begin+1 : end])
				end = -1
				begin = -1
				var mutation ipc.Mutation
				err := proto.Unmarshal(msg, &mutation)
				if err != nil {
					log.Printf("Failed to parse: %x %s\n", msg, err)
					continue
				}
				mutations = append(mutations, &mutation)
			}
		}
	}
	return mutations, nil
}
