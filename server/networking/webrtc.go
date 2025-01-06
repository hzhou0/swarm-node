package main

import (
	"context"
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
	"time"
)

type UUID = string

func NewUUID() UUID {
	id, err := gonanoid.New()
	if err != nil {
		panic(err)
	}
	return id
}

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

type InTrack struct {
	pipeline    *gst.Pipeline
	subscribers map[*WebrtcPeer]*webrtc.TrackLocalStaticSample
}

type WebrtcPeerRole = int

const (
	WebrtcPeerRoleT = iota + 1
	WebrtcPeerRoleB = iota + 1
)

// todo: handle the case where multiple peers offer the same incoming named track
// todo: handle the case where the same named track is both incoming and outgoing

type WebrtcPeer struct {
	pc          *webrtc.PeerConnection
	datachannel *webrtc.DataChannel
	role        WebrtcPeerRole
	outTracks   []NamedTrackKey                 // to peer
	inTracks    map[NamedTrackKey]*gst.Pipeline // from peer
}

type PeeringOffer struct {
	dest      UUID
	sdp       *webrtc.SessionDescription
	outTracks []NamedTrackKey
}

type WebrtcState struct {
	config          webrtc.Configuration
	srcUUID         UUID
	peers           map[UUID]*WebrtcPeer
	allowedInTracks []NamedTrackKey
	outTracks       map[NamedTrackKey]*InTrack // to peer
	ClosePeer       chan *WebrtcPeer
	Close           context.CancelFunc
	AllowedInTracks chan []NamedTrackKey
	PeeringOffers   chan PeeringOffer
}

func (peer *WebrtcPeer) unsafeClose(state *WebrtcState) {
	if peer.outTracks != nil {
		for _, outTrack := range peer.outTracks {
			ot := state.outTracks[outTrack]
			delete(ot.subscribers, peer)
			if len(ot.subscribers) == 0 {
				err := ot.pipeline.SetState(gst.StatePaused)
				if err != nil {
					panic(err)
				}
			}
		}
	}
	if peer.inTracks != nil {
		for _, pipeline := range peer.inTracks {
			err := pipeline.SetState(gst.StateNull)
			if err != nil {
				panic(err)
			}
			pipeline.Unref()
		}
	}
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

func NewWebrtcState() *WebrtcState {
	gst.Init(nil)
	r := &WebrtcState{}
	r.srcUUID = NewUUID()
	r.allowedInTracks = []NamedTrackKey{}
	r.config = webrtc.Configuration{
		ICEServers: []webrtc.ICEServer{
			{
				URLs: []string{"stun:stun.l.google.com:19302"},
			},
		},
	}
	r.AllowedInTracks = make(chan []NamedTrackKey, 1)
	r.PeeringOffers = make(chan PeeringOffer, 1)
	r.ClosePeer = make(chan *WebrtcPeer, 1)
	var ctx context.Context
	ctx, r.Close = context.WithCancel(context.Background())
	go func() {
		for {
			select {
			case <-ctx.Done():
				for _, peer := range r.peers {
					peer.unsafeClose(r)
				}
				return
			case peer := <-r.ClosePeer:
				peer.unsafeClose(r)
			case allowedTracks := <-r.AllowedInTracks:
				r.allowedInTracks = allowedTracks
			case offer := <-r.PeeringOffers:
				r.putPeer(offer)
			}
		}
	}()
	return r
}

func (state *WebrtcState) putPeer(offer PeeringOffer) {
	// If peer exists, Close down its connection and delete it from the map.
	if peer, exists := state.peers[offer.dest]; exists {
		delete(state.peers, offer.dest)
		defer func() {
			state.ClosePeer <- peer
		}()
	}
	newPeer := WebrtcPeer{}
	state.peers[offer.dest] = &newPeer
	newPeer.inTracks = make(map[NamedTrackKey]*gst.Pipeline)
	newPeer.outTracks = offer.outTracks

	var err error
	newPeer.pc, err = webrtc.NewPeerConnection(state.config)
	if err != nil {
		panic(err)
	}
	for _, v := range newPeer.outTracks {
		webrtcTrack, err := webrtc.NewTrackLocalStaticSample(webrtc.RTPCodecCapability{MimeType: v.mimeType}, v.trackId, v.streamId)
		if err != nil {
			panic(err)
		} else if _, err = newPeer.pc.AddTrack(webrtcTrack); err != nil {
			panic(err)
		}
		namedTrack, exists := state.outTracks[v]
		if !exists {
			pipeline := state.pipelineForCodec(v)
			state.outTracks[v] = &InTrack{subscribers: make(map[*WebrtcPeer]*webrtc.TrackLocalStaticSample), pipeline: pipeline}
		}
		namedTrack.subscribers[&newPeer] = webrtcTrack
	}

	state.registerTrackHandlers(&newPeer)

	// Set up data channel depending on role (transmitter creates channel, broadcaster handles it)
	newPeer.pc.OnICEConnectionStateChange(func(s webrtc.ICEConnectionState) {
		if s == webrtc.ICEConnectionStateConnected {
			for _, t := range newPeer.outTracks {
				if err = state.outTracks[t].pipeline.SetState(gst.StatePlaying); err != nil {
					panic(err)
				}
			}
			if newPeer.role == WebrtcPeerRoleT {
				newPeer.datachannel, err = newPeer.pc.CreateDataChannel(state.srcUUID, nil)
				if err != nil {
					panic(err)
				}
				newPeer.datachannel.OnMessage(func(msg webrtc.DataChannelMessage) {
					log.Printf(string(msg.Data))
				})
			}
		}
		if s == webrtc.ICEConnectionStateFailed {
			log.Printf("ICE Connection State for %s failed", offer.dest)
			state.ClosePeer <- &newPeer
		}
	})
	if newPeer.role == WebrtcPeerRoleB {
		newPeer.pc.OnDataChannel(func(d *webrtc.DataChannel) {
			if newPeer.datachannel == nil {
				newPeer.datachannel = d
				newPeer.datachannel.OnMessage(func(msg webrtc.DataChannelMessage) {
					log.Println(msg.Data)
				})
			}
		})
	}

	// Perform SDP Exchange
	if offer.sdp != nil {
		newPeer.role = WebrtcPeerRoleB
		err = newPeer.pc.SetRemoteDescription(*offer.sdp)
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

		//todo: send sdp offer and receive sdp answer
		panic("not implemented")
		//sdpOffer := newPeer.pc.LocalDescription()
		//webrtcAnswer := make(chan webrtc.SessionDescription)
		//go func() {
		//	// Set the remote SessionDescription when received
		//	err = newPeer.pc.SetRemoteDescription(<-webrtcAnswer)
		//	if err != nil {
		//		panic(err)
		//	}
		//}()
	}
}

func (state *WebrtcState) registerTrackHandlers(peer *WebrtcPeer) {
	peer.pc.OnTrack(func(track *webrtc.TrackRemote, rtpReceiver *webrtc.RTPReceiver) {
		trackKey := NewNamedTrackKey(track.ID(), track.StreamID(), track.Codec().MimeType)
		if !slices.Contains(state.allowedInTracks, trackKey) {
			log.Printf("Disallowed track %+v, closing connection\n", trackKey)
			err := peer.pc.Close()
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
					rtcpSendErr := peer.pc.WriteRTCP([]rtcp.Packet{&rtcp.PictureLossIndication{MediaSSRC: uint32(track.SSRC())}})
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
			err := peer.pc.Close()
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

		if _, t := peer.inTracks[trackKey]; t {
			panic("track already exists")
		}
		peer.inTracks[trackKey] = pipeline
		//todo: notify kernel of the new track

		buf := make([]byte, 1500)
		for {
			i, _, readErr := track.Read(buf)
			if readErr != nil {
				log.Printf("Error reading track: %v, closing connection\n", readErr)
				state.ClosePeer <- peer
				break
			}
			appSrc.PushBuffer(gst.NewBufferFromBytes(buf[:i]))
		}
	})
}

func (state *WebrtcState) pipelineForCodec(trackKey NamedTrackKey) *gst.Pipeline {
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

	appSink, err := pipeline.GetElementByName("appsink")
	if err != nil {
		panic(err)
	}

	app.SinkFromElement(appSink).SetCallbacks(&app.SinkCallbacks{
		NewSampleFunc: func(sink *app.Sink) gst.FlowReturn {
			namedTrackVal, exists := state.outTracks[trackKey]
			if !exists {
				return gst.FlowEOS
			}

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
			for _, webrtcTrack := range namedTrackVal.subscribers {
				if err := webrtcTrack.WriteSample(media.Sample{Data: samples, Duration: *buffer.Duration().AsDuration()}); err != nil {
					panic(err) //nolint
				}
			}
			return gst.FlowOK
		},
	})
	return pipeline
}
