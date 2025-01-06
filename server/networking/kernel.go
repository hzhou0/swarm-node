package main

import (
	"bytes"
	"context"
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

func runKernelBackground() (mutationW *os.File, eventR *os.File) {
	kernelEnvVar := os.Getenv("SWARM_NODE_KERNEL")
	if kernelEnvVar == "" {
		log.Fatal("Env Var SWARM_NODE_KERNEL not set")
	}
	var entrypoint string
	switch kernelEnvVar {
	case "december":
		entrypoint = "kernels/december/main.py"
	case "skymap-sens-arr":
		entrypoint = "kernels/skymap/sensor_array/main.py"
	case "skymap-serv":
		entrypoint = "kernels/skymap/server/main.py"
	default:
		log.Fatalf("Unknown kernel %s,exiting", kernelEnvVar)
	}

	venvPath := os.Getenv("SWARM_NODE_KERNEL_VENV")
	if venvPath == "" {
		log.Fatal("Env Var SWARM_NODE_KERNEL_VENV not set")
	}
	activateScript := path.Join(venvPath, "bin", "activate")
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

	mutationR, mutationW, err := os.Pipe()
	if err != nil {
		panic(err)
	}
	eventR, eventW, err := os.Pipe()
	if err != nil {
		panic(err)
	}
	go func() {
		ctx, kill := context.WithCancel(context.Background())
		kernelProc := exec.CommandContext(ctx, "python3", entrypoint)
		kernelProc.Env = append(sourcedEnv, "SWARM_NODE_KERNEL="+kernelEnvVar)
		kernelProc.Stderr = KernelLogWriter{output: os.Stderr, kernelEnvVar: kernelEnvVar}
		kernelProc.Stdout = KernelLogWriter{output: os.Stdout, kernelEnvVar: kernelEnvVar}
		kernelProc.ExtraFiles = []*os.File{mutationR, eventW}
		defer func() {
			// Send SIGTERM
			err := kernelProc.Process.Signal(os.Interrupt)
			if err != nil {
				kill()
			}
			// If process isn't done after 3 seconds, kill it
			select {
			case <-ctx.Done():
				fmt.Printf("Python kernel gracefully destroyed.")
			case <-time.After(3 * time.Second):
				kill()
				fmt.Printf("Python kernel timed out. Killing process.")
			}
			_ = mutationR.Close()
			_ = mutationW.Close()
			_ = eventR.Close()
			_ = eventW.Close()
		}()
		// Kernel is expected to never exit
		err = kernelProc.Run()
		if err != nil {
			panic(err)
		}
		log.Fatalln("Kernel exited! Shutting Down.")
		//"videotestsrc num-buffers=1000 ! videoconvert ! vaapih264enc ! h264parse ! mp4mux ! filesink location=test.mp4"
		//"videotestsrc num-buffers=1000 ! videoconvert ! x264enc ! mp4mux ! filesink location=test.mp4"
		//"filesrc location=test.mp4 ! qtdemux ! avdec_h264 ! videoconvert ! autovideosink"
	}()
	return mutationW, eventR
}

func handleKernelEvents(eventR *os.File) {
	failedCounter := 0
	for {
		events, err := getEvents(eventR)
		if err != nil {
			failedCounter++
			if failedCounter > 3 {
				panic(err)
			}
			continue
		} else {
			failedCounter = 0
		}
		for i := 0; i < len(*events); i++ {
			event := &(*events)[i]
			if event.HasData() {

			}
		}
	}
}

type KernelLogWriter struct {
	output       io.Writer
	kernelEnvVar string
}

func (k KernelLogWriter) Write(p []byte) (n int, err error) {
	return k.output.Write([]byte(fmt.Sprintf("[%s] %s", k.kernelEnvVar, string(p))))
}

func mutate(mutationW *os.File, mutation *ipc.KernelMutation) (err error) {
	encoded, err := proto.Marshal(mutation)
	if err != nil {
		panic(err)
	}
	encoded = cobsEncoder.Encode(encoded)
	encoded = append([]byte{0}, append(encoded, 0)...)
	err = mutationW.SetWriteDeadline(time.Now().Add(1 * time.Second))
	if err != nil {
		return err
	}
	_, err = mutationW.Write(encoded)
	if err != nil {
		return err
	}
	return nil
}

var eventBuf [65536]byte

func getEvents(eventR *os.File) (event *[]ipc.KernelEvent, err error) {
	err = eventR.SetReadDeadline(time.Now().Add(1 * time.Second))
	if err != nil {
		return nil, err
	}
	n, err := eventR.Read(eventBuf[:])
	if n == 0 || err == io.EOF {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	begin := -1
	end := -1
	kernelEvents := make([]ipc.KernelEvent, 5)
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
			err := proto.Unmarshal(msg, &kernelEvents[j])
			if err != nil {
				continue
			}
			j++
			if j >= cap(kernelEvents) {
				newKernelEvents := make([]ipc.KernelEvent, j*2)
				copy(newKernelEvents, kernelEvents)
				kernelEvents = newKernelEvents
			}
		}
	}
	return &kernelEvents, nil
}
