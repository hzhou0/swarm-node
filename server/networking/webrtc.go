package main

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"github.com/go-gst/go-gst/gst"
	"github.com/go-gst/go-gst/gst/app"
	"github.com/matoous/go-nanoid/v2"
	"github.com/pion/rtcp"
	"github.com/pion/webrtc/v4"
	"github.com/pion/webrtc/v4/pkg/media"
	"google.golang.org/protobuf/proto"
	"io"
	"log"
	"maps"
	"net/http"
	"net/url"
	"networking/ipc"
	"os/user"
	"path"
	"slices"
	"strings"
	"sync"
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
	sender      UUID // `""` when outbound
	trackId     string
	streamId    string
	mimeType    string
	shmSinkPath string //Absolute
}

func NewNamedTrackKey(sender UUID, trackId string, streamId string, mimeType string) NamedTrackKey {
	currentUser, err := user.Current()
	if err != nil {
		log.Fatal(err)
	}

	if sender == "" {
		sender = "outbound"
	}

	serialized := fmt.Sprintf("u%s-swarmnode-gst-%s-%s-%s-%s", currentUser.Uid, sender, streamId, trackId, mimeType)
	serialized = strings.ReplaceAll(serialized, "/", "_")
	return NamedTrackKey{sender, streamId, trackId, mimeType, path.Join("/dev/shm", serialized)}
}

type OutTrack struct {
	pipeline    *gst.Pipeline
	subscribers map[*WebrtcPeer]*webrtc.TrackLocalStaticSample
}

type WebrtcPeerRole = int

const (
	WebrtcPeerRoleT = iota + 1
	WebrtcPeerRoleB = iota + 1
)

type WebrtcPeer struct {
	pc          *webrtc.PeerConnection
	datachannel *webrtc.DataChannel
	role        WebrtcPeerRole                  // the local role in this relationship
	outTracks   []NamedTrackKey                 // to peer
	inTracks    map[NamedTrackKey]*gst.Pipeline // from peer
	DataOut     chan []byte
	Close       func()
}

type PeeringOffer struct {
	peerId      UUID
	sdp         *webrtc.SessionDescription
	outTracks   []NamedTrackKey
	inTracks    []NamedTrackKey
	responseSdp chan *webrtc.SessionDescription
}

func NewPeeringOffer(peerId UUID, sdp *webrtc.SessionDescription, outTracks []NamedTrackKey, inTracks []NamedTrackKey) *PeeringOffer {
	n := &PeeringOffer{
		peerId:      peerId,
		sdp:         sdp,
		outTracks:   outTracks,
		inTracks:    inTracks,
		responseSdp: make(chan *webrtc.SessionDescription),
	}
	return n
}

type WebrtcState struct {
	SrcUUID            UUID
	config             webrtc.Configuration
	peers              map[UUID]*WebrtcPeer
	outTrackStates     map[NamedTrackKey]*OutTrack
	outTracks          []NamedTrackKey // the current outbound tracks
	outTracksMu        sync.RWMutex
	InTrack            chan NamedTrackKey         // Receive inbound tracks
	DataOut            chan *ipc.DataTransmission // Send outbound data
	DataIn             chan *ipc.DataTransmission // Receive inbound data
	SetAllowedInTracks chan []NamedTrackKey       // Set the current allowed inbound named tracks
	allowedInTracks    []NamedTrackKey
	allowedInTracksMu  sync.RWMutex
	ClosePeer          chan *WebrtcPeer   // Send a peer here to close it; idempotent
	Close              context.CancelFunc // Destroy all associated resources
	PutPeeringOffers   chan PeeringOffer  // Put new peering offers. Offers must be valid and tracks acceptable to both sides (prenegotiations completed).
}

func NewWebrtcState() *WebrtcState {
	gst.Init(nil)
	ctx, Close := context.WithCancel(context.Background())
	r := &WebrtcState{
		config: webrtc.Configuration{
			ICEServers: []webrtc.ICEServer{
				{
					URLs: []string{"stun:stun.l.google.com:19302"},
				},
			},
		},
		SrcUUID:            NewUUID(),
		peers:              make(map[UUID]*WebrtcPeer),
		allowedInTracks:    nil,
		outTrackStates:     make(map[NamedTrackKey]*OutTrack),
		DataOut:            make(chan *ipc.DataTransmission, 10),
		DataIn:             make(chan *ipc.DataTransmission, 10),
		outTracks:          nil,
		InTrack:            make(chan NamedTrackKey),
		SetAllowedInTracks: make(chan []NamedTrackKey),
		ClosePeer:          make(chan *WebrtcPeer),
		Close:              Close,
		PutPeeringOffers:   make(chan PeeringOffer),
	}

	go func() {
		for {
			select {
			case <-ctx.Done():
				for _, peer := range r.peers {
					peer.Close()
				}
				return
			case peer := <-r.ClosePeer:
				peer.Close()
			case offer := <-r.PutPeeringOffers:
				err := r.PutPeer(offer)
				if err != nil {
					log.Println(err)
				}
			case allowedTracks := <-r.SetAllowedInTracks:
				for _, track := range allowedTracks {
					track.sender = ""
					track.shmSinkPath = ""
				}
				r.allowedInTracksMu.Lock()
				r.allowedInTracks = allowedTracks
				r.allowedInTracksMu.Unlock()
			case dataOut := <-r.DataOut:
				if peer, exist := r.peers[dataOut.GetDestUuid()]; exist {
					dataBytes := dataOut.GetPayload()
					peer.DataOut <- dataBytes
				} else {
					log.Println("Peer does not exist for data send")
				}
			}
		}
	}()
	return r
}

// OutTracks Returns the current outbound track keys
func (state *WebrtcState) OutTracks() []NamedTrackKey {
	state.outTracksMu.RLock()
	defer state.outTracksMu.RUnlock()
	return state.outTracks
}

func (state *WebrtcState) OutTrackAllowed(key NamedTrackKey) bool {
	for _, trackKey := range state.OutTracks() {
		if key.trackId == trackKey.trackId && key.streamId == trackKey.streamId && key.mimeType == trackKey.mimeType {
			return true
		}
	}
	return false
}

func (state *WebrtcState) InTrackAllowed(key NamedTrackKey) bool {
	state.allowedInTracksMu.RLock()
	defer state.allowedInTracksMu.RUnlock()
	for _, trackKey := range state.allowedInTracks {
		if key.trackId == trackKey.trackId && key.streamId == trackKey.streamId && key.mimeType == trackKey.mimeType {
			return true
		}
	}
	return false
}

func (peer *WebrtcPeer) unsafeClose(state *WebrtcState) {
	close(peer.DataOut)
	if peer.outTracks != nil {
		for _, outTrack := range peer.outTracks {
			ot := state.outTrackStates[outTrack]
			delete(ot.subscribers, peer)
			if len(ot.subscribers) == 0 {
				err := ot.pipeline.SetState(gst.StatePaused)
				if err != nil {
					panic(err)
				}
			}
		}
	}
	peer.outTracks = nil
	if peer.inTracks != nil {
		for _, pipeline := range peer.inTracks {
			err := pipeline.SetState(gst.StateNull)
			if err != nil {
				panic(err)
			}
			pipeline.Unref()
		}
	}
	peer.inTracks = nil
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
	peer.pc = nil
}

func (peer *WebrtcPeer) setupDataChannel(offer PeeringOffer, state *WebrtcState) {
	peer.datachannel.OnMessage(func(msg webrtc.DataChannelMessage) {
		trans := ipc.DataTransmission{}
		trans.SetSrcUuid(offer.peerId)
		trans.SetPayload(msg.Data)
		go func() {
			state.DataIn <- &trans
		}()
	})
	go func() {
		for {
			select {
			case trans, ok := <-peer.DataOut:
				if !ok {
					return
				}
				err := peer.datachannel.Send(trans)
				if err != nil {
					panic(err)
				}
			}
		}
	}()
}

func (state *WebrtcState) PutPeer(offer PeeringOffer) error {
	defer func() {
		// In case this operation failed, try to put a nil into offer.responseSdp
		close(offer.responseSdp)
		// This function can alter OutTracks Keys, update it
		state.outTracksMu.Lock()
		defer state.outTracksMu.Unlock()
		state.outTracks = slices.Collect(maps.Keys(state.outTrackStates))
	}()
	// If peerId is none, create the media pipeline and return
	if offer.peerId == "" {
		for _, v := range offer.outTracks {
			_, exists := state.outTrackStates[v]
			if !exists {
				pipeline := state.pipelineForCodec(v)
				state.outTrackStates[v] = &OutTrack{subscribers: make(map[*WebrtcPeer]*webrtc.TrackLocalStaticSample), pipeline: pipeline}
			}
		}
		return nil
	}

	// If peer already exists, close down its connection and delete it from the map.
	if peer, exists := state.peers[offer.peerId]; exists {
		delete(state.peers, offer.peerId)
		go func() {
			state.ClosePeer <- peer
		}()
	}

	// Create a new peer
	newPeer := WebrtcPeer{}
	state.peers[offer.peerId] = &newPeer
	newPeer.inTracks = make(map[NamedTrackKey]*gst.Pipeline)
	newPeer.outTracks = offer.outTracks
	newPeer.DataOut = make(chan []byte, 10)
	newPeer.Close = sync.OnceFunc(func() { newPeer.unsafeClose(state) })
	if offer.sdp != nil {
		newPeer.role = WebrtcPeerRoleB
	} else {
		newPeer.role = WebrtcPeerRoleT
	}

	var err error
	newPeer.pc, err = webrtc.NewPeerConnection(state.config)
	if err != nil {
		return err
	}
	for _, v := range newPeer.outTracks {
		webrtcTrack, err := webrtc.NewTrackLocalStaticSample(webrtc.RTPCodecCapability{MimeType: v.mimeType}, v.trackId, v.streamId)
		if err != nil {
			newPeer.Close()
			return err
		} else if _, err = newPeer.pc.AddTrack(webrtcTrack); err != nil {
			newPeer.Close()
			return err
		}
		namedTrack, exists := state.outTrackStates[v]
		if !exists {
			pipeline := state.pipelineForCodec(v)
			state.outTrackStates[v] = &OutTrack{subscribers: make(map[*WebrtcPeer]*webrtc.TrackLocalStaticSample), pipeline: pipeline}
		}
		namedTrack.subscribers[&newPeer] = webrtcTrack
	}

	state.registerTrackHandlers(&newPeer, offer.peerId)

	newPeer.pc.OnICEConnectionStateChange(func(s webrtc.ICEConnectionState) {
		if s == webrtc.ICEConnectionStateConnected {
			log.Printf("Connected %s->%s", state.SrcUUID, offer.peerId)
			for _, t := range newPeer.outTracks {
				if err = state.outTrackStates[t].pipeline.SetState(gst.StatePlaying); err != nil {
					log.Println(err)
					state.ClosePeer <- &newPeer
					return
				}
			}
		}
		if s == webrtc.ICEConnectionStateFailed {
			log.Printf("ICE Connection State for %s failed", offer.peerId)
			state.ClosePeer <- &newPeer
		}
	})

	// Set up data channel depending on role (transmitter creates channel, broadcaster handles it)
	if newPeer.role == WebrtcPeerRoleB {
		newPeer.pc.OnDataChannel(func(d *webrtc.DataChannel) {
			fmt.Println("Data channel received connected")
			if newPeer.datachannel == nil {
				newPeer.datachannel = d
				newPeer.setupDataChannel(offer, state)
			}
		})
	} else if newPeer.role == WebrtcPeerRoleT {
		newPeer.datachannel, err = newPeer.pc.CreateDataChannel(state.SrcUUID, nil)
		if err != nil {
			log.Println(err)
			newPeer.Close()
			return err
		}
		newPeer.setupDataChannel(offer, state)
	}

	// Perform SDP Exchange
	if newPeer.role == WebrtcPeerRoleB {
		err = newPeer.pc.SetRemoteDescription(*offer.sdp)
		if err != nil {
			newPeer.Close()
			return err
		}

		answer, err := newPeer.pc.CreateAnswer(nil)
		if err != nil {
			newPeer.Close()
			return err
		}

		// Create channel that is blocked until ICE Gathering is complete
		gatherComplete := webrtc.GatheringCompletePromise(newPeer.pc)

		// Sets the LocalDescription, and starts our UDP listeners
		err = newPeer.pc.SetLocalDescription(answer)
		if err != nil {
			newPeer.Close()
			return err
		}

		<-gatherComplete

		offer.responseSdp <- newPeer.pc.LocalDescription()
	} else {
		// For outgoing requests, peerId must be a valid URI
		// No other IDs are currently supported
		// This must be at step 3: both local_tracks and remote_tracks must be wanted
		if _, err := url.ParseRequestURI(offer.peerId); err != nil {
			newPeer.Close()
			return err
		}

		sdpOffer, err := newPeer.pc.CreateOffer(nil)
		if err != nil {
			newPeer.Close()
			return err
		}

		// Create channel that is blocked until ICE Gathering is complete
		gatherComplete := webrtc.GatheringCompletePromise(newPeer.pc)

		// Sets the LocalDescription, and starts our UDP listeners
		if err = newPeer.pc.SetLocalDescription(sdpOffer); err != nil {
			newPeer.Close()
			return err
		}
		<-gatherComplete

		newOffer := ipc.WebrtcOffer{}
		newOffer.SetSrcUuid(state.SrcUUID)
		localSDPOffer := newPeer.pc.LocalDescription()
		newOffer.SetSdp(localSDPOffer.SDP)
		newOffer.SetType(localSDPOffer.Type.String())
		var localTracks []*ipc.NamedTrack
		for _, tr := range offer.outTracks {
			localTrack := ipc.NamedTrack{}
			localTrack.SetTrackId(tr.trackId)
			localTrack.SetStreamId(tr.streamId)
			localTrack.SetMimeType(tr.mimeType)
			localTracks = append(localTracks, &localTrack)
		}
		newOffer.SetLocalTracks(localTracks)
		newOffer.SetLocalTracksSet(true)
		var remoteTracks []*ipc.NamedTrack
		for _, tr := range offer.outTracks {
			remoteTrack := ipc.NamedTrack{}
			remoteTrack.SetTrackId(tr.trackId)
			remoteTrack.SetStreamId(tr.streamId)
			remoteTrack.SetMimeType(tr.mimeType)
			remoteTracks = append(remoteTracks, &remoteTrack)
		}
		newOffer.SetRemoteTracks(remoteTracks)
		newOffer.SetRemoteTracksSet(true)
		payload, err := proto.Marshal(&newOffer)
		if err != nil {
			newPeer.Close()
			return err
		}

		// Set the remote SessionDescription when received
		client := http.Client{Timeout: 10 * time.Second}
		resp, err := client.Post(offer.peerId, "application/x-protobuf", bytes.NewReader(payload))
		if err != nil {
			newPeer.Close()
			return err
		}
		if resp.StatusCode < 200 || resp.StatusCode > 300 {
			return errors.New(fmt.Sprintf("Unsuccessful HTTP Status: %d", resp.StatusCode))
		}
		defer func() {
			err := resp.Body.Close()
			if err != nil {
				panic(err)
			}
		}()
		respBytes, err := io.ReadAll(resp.Body)
		if err != nil {
			newPeer.Close()
			return err
		}
		answer := ipc.WebrtcOffer{}
		err = proto.Unmarshal(respBytes, &answer)
		if err != nil {
			newPeer.Close()
			return err
		}
		answerSdp := webrtc.SessionDescription{
			Type: webrtc.NewSDPType(answer.GetType()),
			SDP:  answer.GetSdp(),
		}
		err = newPeer.pc.SetRemoteDescription(answerSdp)
		if err != nil {
			newPeer.Close()
			return err
		}
	}
	return nil
}

func (state *WebrtcState) registerTrackHandlers(peer *WebrtcPeer, peerId UUID) {
	peer.pc.OnTrack(func(track *webrtc.TrackRemote, rtpReceiver *webrtc.RTPReceiver) {
		trackKey := NewNamedTrackKey(peerId, track.ID(), track.StreamID(), track.Codec().MimeType)
		if state.InTrackAllowed(trackKey) {
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
		go func() {
			state.InTrack <- trackKey
		}()

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
			namedTrackVal, exists := state.outTrackStates[trackKey]
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
