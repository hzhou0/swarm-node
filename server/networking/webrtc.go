package main

import (
	"fmt"
	"github.com/go-gst/go-gst/gst"
	"github.com/go-gst/go-gst/gst/app"
	"github.com/matoous/go-nanoid/v2"
	"github.com/pion/rtcp"
	"github.com/pion/webrtc/v4"
	"github.com/pion/webrtc/v4/pkg/media"
	"log"
	"os/user"
	"path"
	"slices"
	"strings"
	"sync"
	"time"
)

type NamedTrackKey struct {
	trackId     string
	streamId    string
	mimeType    string
	shmSinkPath string //Absolute
}

func NewNamedTrackKey(trackId string, streamId string, mimeType string) NamedTrackKey {
	currentUser, err := user.Current()
	if err != nil {
		log.Fatal(err)
	}

	serialized := fmt.Sprintf("u%s-swarmnode-gst-%s-%s-%s", currentUser.Uid, streamId, trackId, mimeType)
	serialized = strings.ReplaceAll(serialized, "/", "_")
	return NamedTrackKey{streamId, trackId, mimeType, path.Join("/dev/shm", serialized)}
}

type NamedTrackValue struct {
	pipeline    *gst.Pipeline
	sampleTrack *webrtc.TrackLocalStaticSample
}

type UUID = string

func NewUUID() UUID {
	id, err := gonanoid.New()
	if err != nil {
		panic(err)
	}
	return id
}

type WebrtcPeerRole = int

const (
	WebrtcPeerRoleT = iota + 1
	WebrtcPeerRoleB = iota + 1
)

type webrtcPeer struct {
	pc           *webrtc.PeerConnection
	datachannel  *webrtc.DataChannel
	incomingData chan []byte
	role         WebrtcPeerRole
	outTracks    map[NamedTrackKey]*NamedTrackValue // to peer
	inTracks     map[NamedTrackKey]*NamedTrackValue // from peer
	sync.Mutex
}

func (peer *webrtcPeer) Close() {
	peer.Lock()
	defer peer.Unlock()
	if peer.pc != nil {
		err := peer.pc.GracefulClose()
		if err != nil {
			log.Printf("Graceful Peer Connection Close Failed: %v \n", err)
			log.Println("Attempting Force Close")
			err := peer.pc.Close()
			if err != nil {
				panic(err)
			}
		}
	}
}

type webrtcState struct {
	config  webrtc.Configuration
	srcUUID UUID
	peers   map[UUID]*webrtcPeer
	sync.Mutex
	allowedTracks []NamedTrackKey
}

func (r *webrtcState) init(allowedTracks []NamedTrackKey) {
	r.srcUUID = NewUUID()
	r.allowedTracks = allowedTracks
	gst.Init(nil)
	r.config = webrtc.Configuration{
		ICEServers: []webrtc.ICEServer{
			{
				URLs: []string{"stun:stun.l.google.com:19302"},
			},
		},
	}
}

func (r *webrtcState) putPeer(dest UUID, sdp *webrtc.SessionDescription, outTracks map[NamedTrackKey]*NamedTrackValue) (*webrtc.SessionDescription, chan<- webrtc.SessionDescription) {
	r.Lock()
	// If peer exists, Close down its connection and delete it from the map.
	if peer, exists := r.peers[dest]; exists {
		delete(r.peers, dest)
		go peer.Close()
	}
	newPeer := webrtcPeer{}
	newPeer.Lock()
	defer newPeer.Unlock()
	r.peers[dest] = &newPeer
	r.Unlock()
	newPeer.incomingData = make(chan []byte, 16384)
	newPeer.inTracks = make(map[NamedTrackKey]*NamedTrackValue)
	newPeer.outTracks = outTracks

	var err error
	newPeer.pc, err = webrtc.NewPeerConnection(r.config)
	if err != nil {
		panic(err)
	}
	for k, v := range newPeer.outTracks {
		track, err := webrtc.NewTrackLocalStaticSample(webrtc.RTPCodecCapability{MimeType: k.mimeType}, k.trackId, k.streamId)
		if err != nil {
			panic(err)
		} else if _, err = newPeer.pc.AddTrack(track); err != nil {
			panic(err)
		}
		v.sampleTrack = track
	}

	registerTrackHandlers(&newPeer, &r.allowedTracks)

	// Set up data channel depending on role (transmitter creates channel, broadcaster handles it)
	newPeer.pc.OnICEConnectionStateChange(func(s webrtc.ICEConnectionState) {
		if s == webrtc.ICEConnectionStateConnected {
			newPeer.Lock()
			defer newPeer.Unlock()
			for k, v := range newPeer.outTracks {
				pipelineForCodec(k, v)
			}
			if newPeer.role == WebrtcPeerRoleT {
				newPeer.datachannel, err = newPeer.pc.CreateDataChannel(r.srcUUID, nil)
				if err != nil {
					panic(err)
				}
				newPeer.datachannel.OnMessage(func(msg webrtc.DataChannelMessage) {
					newPeer.incomingData <- msg.Data
				})
			}
		}
		if s == webrtc.ICEConnectionStateFailed {
			log.Printf("ICE Connection State for %s failed", dest)
			go newPeer.Close()
		}
	})
	if newPeer.role == WebrtcPeerRoleB {
		newPeer.pc.OnDataChannel(func(d *webrtc.DataChannel) {
			if newPeer.datachannel == nil {
				newPeer.datachannel = d
				newPeer.datachannel.OnMessage(func(msg webrtc.DataChannelMessage) {
					newPeer.incomingData <- msg.Data
				})
			}
		})
	}

	// Perform SDP Exchange
	if sdp != nil {
		newPeer.role = WebrtcPeerRoleB
		err = newPeer.pc.SetRemoteDescription(*sdp)
		if err != nil {
			panic(err)
		}

		answer, err := newPeer.pc.CreateAnswer(nil)
		if err != nil {
			panic(err)
		}

		// Create channel that is blocked until ICE Gathering is complete
		gatherComplete := webrtc.GatheringCompletePromise(newPeer.pc)

		// Sets the LocalDescription, and starts our UDP listeners
		err = newPeer.pc.SetLocalDescription(answer)
		if err != nil {
			panic(err)
		}

		<-gatherComplete
	} else {
		newPeer.role = WebrtcPeerRoleT
		offer, err := newPeer.pc.CreateOffer(nil)
		if err != nil {
			panic(err)
		}

		// Create channel that is blocked until ICE Gathering is complete
		gatherComplete := webrtc.GatheringCompletePromise(newPeer.pc)

		// Sets the LocalDescription, and starts our UDP listeners
		if err = newPeer.pc.SetLocalDescription(offer); err != nil {
			panic(err)
		}
		<-gatherComplete

		webrtcAnswer := make(chan webrtc.SessionDescription)
		go func() {
			// Set the remote SessionDescription when received
			err = newPeer.pc.SetRemoteDescription(<-webrtcAnswer)
			if err != nil {
				panic(err)
			}
		}()
		return newPeer.pc.LocalDescription(), webrtcAnswer
	}
	return nil, nil
}

func registerTrackHandlers(newPeer *webrtcPeer, allowedTracks *[]NamedTrackKey) {
	newPeer.pc.OnTrack(func(track *webrtc.TrackRemote, rtpReceiver *webrtc.RTPReceiver) {
		trackKey := NewNamedTrackKey(track.ID(), track.StreamID(), track.Codec().MimeType)
		if !slices.Contains(*allowedTracks, trackKey) {
			log.Printf("Disallowed track %+v, closing connection\n", trackKey)
			err := newPeer.pc.Close()
			if err != nil {
				panic(err)
			}
			return
		}

		if track.Kind() == webrtc.RTPCodecTypeVideo {
			// Send a PLI on an interval so that the publisher is pushing a keyframe every rtcpPLIInterval
			go func() {
				ticker := time.NewTicker(time.Second * 3)
				for range ticker.C {
					rtcpSendErr := newPeer.pc.WriteRTCP([]rtcp.Packet{&rtcp.PictureLossIndication{MediaSSRC: uint32(track.SSRC())}})
					if rtcpSendErr != nil {
						fmt.Println(rtcpSendErr)
					}
				}
			}()
		}

		log.Printf("Track has started, of type %d: %s \n", track.PayloadType(), track.Codec().MimeType)

		pipelineString := "appsrc format=time is-live=true do-timestamp=true name=src ! application/x-rtp"
		sinkString := fmt.Sprintf("shmsink socket=%s shm-size=67108864 wait-for-connection=true", trackKey.shmSinkPath)
		switch strings.ToLower(track.Codec().MimeType) {
		case "video/vp8":
			pipelineString += fmt.Sprintf(", payload=%d, encoding-name=VP8-DRAFT-IETF-01 ! rtpvp8depay ! ", track.PayloadType())
		case "video/opus":
			pipelineString += fmt.Sprintf(", payload=%d, encoding-name=OPUS ! rtpopusdepay ! ", track.PayloadType())
		case "video/vp9":
			pipelineString += " ! rtpvp9depay ! "
		case "video/h264":
			pipelineString += " ! rtph264depay ! "
		case "audio/g722":
			pipelineString += " clock-rate=8000 ! rtpg722depay ! "
		default:
			log.Printf("Unhandled codec %s, closing connection \n", track.Codec().MimeType)
			err := newPeer.pc.Close()
			if err != nil {
				panic(err)
			}
			return
		}
		pipelineString += sinkString
		pipeline, err := gst.NewPipelineFromString(pipelineString)
		if err != nil {
			panic(err)
		}
		if err = pipeline.SetState(gst.StatePlaying); err != nil {
			panic(err)
		}
		appEle, err := pipeline.GetElementByName("src")
		if err != nil {
			panic(err)
		}
		appSrc := app.SrcFromElement(appEle)

		newPeer.Lock()
		if _, t := newPeer.inTracks[trackKey]; t {
			panic("track already exists")
		}
		newPeer.inTracks[trackKey] = &NamedTrackValue{pipeline, nil}
		//todo: notify kernel of the new track
		newPeer.Unlock()

		buf := make([]byte, 1500)
		for {
			i, _, readErr := track.Read(buf)
			if readErr != nil {
				log.Printf("Error reading track: %v, closing connection\n", readErr)
				err := newPeer.pc.Close()
				if err != nil {
					panic(err)
				}
				return
			}
			appSrc.PushBuffer(gst.NewBufferFromBytes(buf[:i]))
		}
	})
}

func pipelineForCodec(trackKey NamedTrackKey, trackVal *NamedTrackValue) {
	pipelineStr := "appsink name=appsink"
	pipelineSrc := fmt.Sprintf("shmsrc socket-path=%s is-live=true", trackKey.shmSinkPath)
	switch trackKey.mimeType {
	case "video/vp8":
		pipelineStr = pipelineSrc + " ! vp8enc error-resilient=partitions keyframe-max-dist=10 auto-alt-ref=true cpu-used=5 deadline=1 ! " + pipelineStr
	case "video/vp9":
		pipelineStr = pipelineSrc + " ! vp9enc ! " + pipelineStr
	case "video/h264":
		pipelineStr = pipelineSrc + " ! video/x-raw,format=I420 ! x264enc speed-preset=ultrafast tune=zerolatency key-int-max=20 ! video/x-h264,stream-format=byte-stream ! " + pipelineStr
	case "audio/opus":
		pipelineStr = pipelineSrc + " ! opusenc ! " + pipelineStr
	case "audio/pcmu":
		pipelineStr = pipelineSrc + " ! audio/x-raw, rate=8000 ! mulawenc ! " + pipelineStr
	case "audio/pcma":
		pipelineStr = pipelineSrc + " ! audio/x-raw, rate=8000 ! alawenc ! " + pipelineStr
	default:
		panic("Unhandled codec " + trackKey.mimeType)
	}

	pipeline, err := gst.NewPipelineFromString(pipelineStr)
	if err != nil {
		panic(err)
	}
	trackVal.pipeline = pipeline

	if err = pipeline.SetState(gst.StatePlaying); err != nil {
		panic(err)
	}

	appSink, err := pipeline.GetElementByName("appsink")
	if err != nil {
		panic(err)
	}

	app.SinkFromElement(appSink).SetCallbacks(&app.SinkCallbacks{
		NewSampleFunc: func(sink *app.Sink) gst.FlowReturn {
			sample := sink.PullSample()
			if sample == nil {
				return gst.FlowEOS
			}

			buffer := sample.GetBuffer()
			if buffer == nil {
				return gst.FlowError
			}

			samples := buffer.Map(gst.MapRead).Bytes()
			defer buffer.Unmap()

			if err := trackVal.sampleTrack.WriteSample(media.Sample{Data: samples, Duration: *buffer.Duration().AsDuration()}); err != nil {
				panic(err) //nolint
			}

			return gst.FlowOK
		},
	})
}
