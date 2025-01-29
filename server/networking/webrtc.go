package main

import (
	"context"
	"errors"
	"fmt"
	"github.com/go-gst/go-gst/gst"
	"github.com/go-gst/go-gst/gst/app"
	"github.com/go-resty/resty/v2"
	"github.com/matoous/go-nanoid/v2"
	"github.com/pion/rtcp"
	"github.com/pion/webrtc/v4"
	"github.com/pion/webrtc/v4/pkg/media"
	"google.golang.org/protobuf/proto"
	"log"
	"maps"
	"net/url"
	"networking/ipc"
	"os"
	"path"
	"slices"
	"strings"
	"sync"
	"time"
)

type UUID = string

var client = resty.New()

func NewUUID() UUID {
	id, err := gonanoid.New()
	if err != nil {
		panic(err)
	}
	return id
}

type NamedTrackKey struct {
	sender   UUID // `""` when outbound
	trackId  string
	streamId string
	mimeType string
	shmPath  string //Absolute
}

func NewNamedTrackKey(sender UUID, trackId string, streamId string, mimeType string) NamedTrackKey {
	dirPath := "/tmp/swarmnode-network"
	err := os.MkdirAll(dirPath, 0777)
	if err != nil {
		log.Fatal(err)
	}

	if sender == "" {
		sender = "outbound"
	}

	serialized := fmt.Sprintf("gst|%s|%s|%s|%s", sender, streamId, trackId, mimeType)
	serialized = strings.ReplaceAll(serialized, "/", "_")
	return NamedTrackKey{sender, trackId, streamId, mimeType, path.Join(dirPath, serialized)}
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
	dataOut     chan []byte
	Close       func()
}

type PeeringOffer struct {
	peerId    UUID
	sdp       *webrtc.SessionDescription
	outTracks []NamedTrackKey
	inTracks  []NamedTrackKey
}

func NewPeeringOffer(peerId UUID, sdp *webrtc.SessionDescription, outTracks []NamedTrackKey, inTracks []NamedTrackKey) *PeeringOffer {
	n := &PeeringOffer{
		peerId:    peerId,
		sdp:       sdp,
		outTracks: outTracks,
		inTracks:  inTracks,
	}
	return n
}

func (po *PeeringOffer) Prenegotiate(state *WebrtcState) error {
	// To initiate pre-negotiation, peerId must be a valid URI
	// No other IDs are currently supported
	if _, err := url.ParseRequestURI(po.peerId); err != nil {
		return err
	}
	query := ipc.WebrtcOffer{}
	var localTracks []*ipc.NamedTrack
	for _, ot := range po.outTracks {
		tr := ipc.NamedTrack{}
		tr.SetStreamId(ot.streamId)
		tr.SetTrackId(ot.trackId)
		tr.SetMimeType(ot.mimeType)
		localTracks = append(localTracks, &tr)
	}
	query.SetSrcUuid(state.SrcUUID)
	query.SetLocalTracks(localTracks)
	query.SetLocalTracksSet(true)
	query.SetRemoteTracksSet(false)
	payload, err := proto.Marshal(&query)
	if err != nil {
		return err
	}
	resp, err := client.R().SetHeader("Content-Type", "application/x-protobuf").SetBody(payload).Put(po.peerId)
	if err != nil {
		return err
	}
	if resp.StatusCode() < 200 || resp.StatusCode() > 300 {
		return errors.New(fmt.Sprintf("unsuccessful HTTP Status: %d", resp.StatusCode()))
	}
	answer := ipc.WebrtcOffer{}
	err = proto.Unmarshal(resp.Body(), &answer)
	if err != nil {
		return err
	}
	if !(answer.HasLocalTracksSet() && answer.HasRemoteTracksSet()) {
		return errors.New("answer does not have local or remote tracks set")
	}
	var allowedRemote []NamedTrackKey
	for _, track := range answer.GetLocalTracks() {
		k := NewNamedTrackKey("", track.GetTrackId(), track.GetStreamId(), track.GetMimeType())
		if state.InTrackAllowed(k) {
			allowedRemote = append(allowedRemote, k)
		}
	}
	var allowedLocal []NamedTrackKey
	for _, track := range answer.GetRemoteTracks() {
		k := NewNamedTrackKey("", track.GetTrackId(), track.GetStreamId(), track.GetMimeType())
		if state.OutTrackAllowed(k) {
			allowedLocal = append(allowedLocal, k)
		}
	}
	po.outTracks = allowedLocal
	po.inTracks = allowedRemote
	return nil
}

type WebrtcState struct {
	SrcUUID           UUID
	config            webrtc.Configuration
	peers             map[UUID]*WebrtcPeer
	peersMu           sync.RWMutex
	outTrackStates    map[NamedTrackKey]*OutTrack
	outTracks         []NamedTrackKey // the current outbound tracks
	outTracksMu       sync.RWMutex
	InTrack           chan NamedTrackKey         // Receive inbound tracks
	DataOut           chan *ipc.DataTransmission // Send outbound data
	DataIn            chan *ipc.DataTransmission // Receive inbound data
	allowedInTracks   []NamedTrackKey
	allowedInTracksMu sync.RWMutex
	Close             context.CancelFunc // Destroy all associated resources
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
		SrcUUID:         NewUUID(),
		peers:           make(map[UUID]*WebrtcPeer),
		allowedInTracks: nil,
		outTrackStates:  make(map[NamedTrackKey]*OutTrack),
		DataOut:         make(chan *ipc.DataTransmission, 100),
		DataIn:          make(chan *ipc.DataTransmission, 100),
		outTracks:       nil,
		InTrack:         make(chan NamedTrackKey),
		Close:           Close,
	}

	go func() {
		for {
			select {
			case <-ctx.Done():
				for _, peer := range r.peers {
					peer.Close()
				}
				return
			case dataOut := <-r.DataOut:
				r.peersMu.RLock()
				if peer, exist := r.peers[dataOut.GetDestUuid()]; exist {
					dataBytes := dataOut.GetPayload()
					peer.dataOut <- dataBytes
				} else {
					log.Println("Peer does not exist for data send")
				}
				r.peersMu.RUnlock()
			}
		}
	}()
	return r
}

func (state *WebrtcState) SetAllowedInTracks(allowed []NamedTrackKey) {
	for _, track := range allowed {
		track.sender = ""
		track.shmPath = ""
	}
	state.allowedInTracksMu.Lock()
	state.allowedInTracks = allowed
	state.allowedInTracksMu.Unlock()
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

func (peer *WebrtcPeer) unsafeClose(key string, state *WebrtcState) {
	log.Printf("Closing local->%s\n", key)
	state.peersMu.Lock()
	delete(state.peers, key)
	state.peersMu.Unlock()
	close(peer.dataOut)
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
	pc := peer.pc
	peer.pc = nil
	if pc != nil {
		err := pc.GracefulClose()
		if err != nil {
			log.Printf("Graceful Peer Connection Close Failed: %v \n", err)
			log.Println("Attempting Force Close")
			err := pc.Close()
			if err != nil {
				panic(err)
			}
		}
	}
	log.Printf("Closed local->%s\n", key)
	go func() {
		deletion := ipc.WebrtcOffer{}
		deletion.SetSrcUuid(state.SrcUUID)
		body, err := proto.Marshal(&deletion)
		if err != nil {
			panic(err)
		}
		_, err = client.R().SetBody(body).Delete(key)
		if err != nil {
			return
		}
	}()
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
			trans, ok := <-peer.dataOut
			if !ok {
				return
			}
			err := peer.datachannel.Send(trans)
			if err != nil {
				panic(err)
			}
		}
	}()
}

// Peer [thread safe], create a peer given main.PeeringOffer.
// 1. peerId==nil: create the media pipelines for outTracks and exit.
// 2. sdp ==nil: `peerId` must be a POST URL that accepts ipc.WebrtcOffer. Assume the T role and nil is returned. `offer.outTracks` and `offer.inTracks` will be modified with Prenegotiate().
// 3. sdp!=nil: `peerId` can be any string. Assume the B role and a webrtc.SessionDescription answer is returned.
func (state *WebrtcState) Peer(offer PeeringOffer) (err error, ans *webrtc.SessionDescription) {
	defer func() {
		state.outTracksMu.Lock()
		defer state.outTracksMu.Unlock()
		state.outTracks = slices.Collect(maps.Keys(state.outTrackStates))
	}()
	// Always create the outTracks
	for _, v := range offer.outTracks {
		_, exists := state.outTrackStates[v]
		if !exists {
			pipeline := state.pipelineForCodec(v)
			state.outTrackStates[v] = &OutTrack{subscribers: make(map[*WebrtcPeer]*webrtc.TrackLocalStaticSample), pipeline: pipeline}
		}
	}
	state.outTracksMu.Lock()
	state.outTracks = slices.Collect(maps.Keys(state.outTrackStates))
	state.outTracksMu.Unlock()
	// If peerId is none, create the media pipeline and return
	if offer.peerId == "" {
		return nil, nil
	}

	state.peersMu.Lock()
	// If peer already exists, close down its connection and delete it from the map.
	_, exists := state.peers[offer.peerId]
	if exists {
		return errors.New("peer already exists"), nil
	}
	// Create a new peer
	newPeer := &WebrtcPeer{}
	state.peers[offer.peerId] = newPeer
	state.peersMu.Unlock()

	defer func() {
		if err != nil {
			log.Printf("Peering failed: %v", err)
			newPeer.Close()
		}
	}()

	if offer.sdp != nil {
		newPeer.role = WebrtcPeerRoleB
	} else {
		newPeer.role = WebrtcPeerRoleT
		err = offer.Prenegotiate(state)
		if err != nil {
			return err, nil
		}
	}
	newPeer.inTracks = make(map[NamedTrackKey]*gst.Pipeline)
	newPeer.outTracks = offer.outTracks
	newPeer.dataOut = make(chan []byte, 10)
	newPeer.Close = sync.OnceFunc(func() { newPeer.unsafeClose(offer.peerId, state) })

	newPeer.pc, err = webrtc.NewPeerConnection(state.config)
	if err != nil {
		return err, nil
	}
	for _, v := range newPeer.outTracks {
		var webrtcTrack *webrtc.TrackLocalStaticSample
		webrtcTrack, err = webrtc.NewTrackLocalStaticSample(webrtc.RTPCodecCapability{MimeType: v.mimeType}, v.trackId, v.streamId)
		if err != nil {
			newPeer.Close()
			return err, nil
		} else if _, err = newPeer.pc.AddTrack(webrtcTrack); err != nil {
			newPeer.Close()
			return err, nil
		}
		namedTrack, exists := state.outTrackStates[v]
		if !exists {
			pipeline := state.pipelineForCodec(v)
			state.outTrackStates[v] = &OutTrack{subscribers: make(map[*WebrtcPeer]*webrtc.TrackLocalStaticSample), pipeline: pipeline}
		}
		namedTrack.subscribers[newPeer] = webrtcTrack
	}

	newPeer.registerTrackHandlers(state, offer.peerId)

	newPeer.pc.OnICEConnectionStateChange(func(s webrtc.ICEConnectionState) {
		log.Printf("ICE %s %s->%s", strings.ToUpper(s.String()), state.SrcUUID, offer.peerId)
		switch s {
		case webrtc.ICEConnectionStateConnected:
			for _, t := range newPeer.outTracks {
				if err = state.outTrackStates[t].pipeline.Start(); err != nil {
					log.Println(err)
					go newPeer.Close()
					return
				}
			}
		case webrtc.ICEConnectionStateFailed:
			go newPeer.Close()
		default:
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
			return err, nil
		}
		newPeer.setupDataChannel(offer, state)
	}

	// Perform SDP Exchange
	if newPeer.role == WebrtcPeerRoleB {
		err = newPeer.pc.SetRemoteDescription(*offer.sdp)
		if err != nil {
			newPeer.Close()
			return err, nil
		}

		var answer webrtc.SessionDescription
		answer, err = newPeer.pc.CreateAnswer(nil)
		if err != nil {
			newPeer.Close()
			return err, nil
		}

		// Create channel that is blocked until ICE Gathering is complete
		gatherComplete := webrtc.GatheringCompletePromise(newPeer.pc)

		// Sets the LocalDescription, and starts our UDP listeners
		err = newPeer.pc.SetLocalDescription(answer)
		if err != nil {
			newPeer.Close()
			return err, nil
		}

		<-gatherComplete

		return nil, newPeer.pc.LocalDescription()
	} else {
		// For outgoing requests, peerId must be a valid URI
		// No other IDs are currently supported
		// This must be at step 3: both local_tracks and remote_tracks must be wanted
		if _, err = url.ParseRequestURI(offer.peerId); err != nil {
			return err, nil
		}

		var sdpOffer webrtc.SessionDescription
		sdpOffer, err = newPeer.pc.CreateOffer(nil)
		if err != nil {
			return err, nil
		}

		// Create channel that is blocked until ICE Gathering is complete
		gatherComplete := webrtc.GatheringCompletePromise(newPeer.pc)

		// Sets the LocalDescription, and starts our UDP listeners
		if err = newPeer.pc.SetLocalDescription(sdpOffer); err != nil {
			return err, nil
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
		for _, tr := range offer.inTracks {
			remoteTrack := ipc.NamedTrack{}
			remoteTrack.SetTrackId(tr.trackId)
			remoteTrack.SetStreamId(tr.streamId)
			remoteTrack.SetMimeType(tr.mimeType)
			remoteTracks = append(remoteTracks, &remoteTrack)
		}
		newOffer.SetRemoteTracks(remoteTracks)
		newOffer.SetRemoteTracksSet(true)
		var payload []byte
		payload, err = proto.Marshal(&newOffer)
		if err != nil {
			return err, nil
		}
		// Set the remote SessionDescription when received
		var resp *resty.Response
		resp, err = client.R().SetHeader("Content-Type", "application/x-protobuf").SetBody(payload).Put(offer.peerId)
		if err != nil {
			return err, nil
		}
		if resp.StatusCode() < 200 || resp.StatusCode() > 300 {
			err = errors.New(fmt.Sprintf("Unsuccessful HTTP Status: %d", resp.StatusCode()))
			return err, nil
		}
		answer := ipc.WebrtcOffer{}
		err = proto.Unmarshal(resp.Body(), &answer)
		if err != nil {
			return err, nil
		}
		answerSdp := webrtc.SessionDescription{
			Type: webrtc.NewSDPType(answer.GetType()),
			SDP:  answer.GetSdp(),
		}
		err = newPeer.pc.SetRemoteDescription(answerSdp)
		if err != nil {
			return err, nil
		}
	}
	return nil, nil
}

// UnPeer [thread safe] Remove this peer if it exists, no-op if it doesn't.
func (state *WebrtcState) UnPeer(peerId UUID) {
	state.peersMu.RLock()
	peer, exists := state.peers[peerId]
	state.peersMu.RUnlock()
	if !exists {
		return
	}
	peer.Close()
}

func (peer *WebrtcPeer) registerTrackHandlers(state *WebrtcState, peerId UUID) {
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
					if peer.pc == nil {
						return
					}
					rtcpSendErr := peer.pc.WriteRTCP([]rtcp.Packet{&rtcp.PictureLossIndication{MediaSSRC: uint32(track.SSRC())}})
					if rtcpSendErr != nil {
						log.Println(rtcpSendErr)
					}
				}
			}()
		}

		log.Printf("Track has started, of type %d: %s \n", track.PayloadType(), track.Codec().MimeType)

		pipelineString := "appsrc format=time is-live=true do-timestamp=true name=src ! application/x-rtp"
		sinkString := fmt.Sprintf("shmsink socket-path=%s shm-size=67108864 wait-for-connection=true", trackKey.shmPath)
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
				peer.Close()
				break
			}
			appSrc.PushBuffer(gst.NewBufferFromBytes(buf[:i]))
		}
	})
}

func (state *WebrtcState) pipelineForCodec(trackKey NamedTrackKey) *gst.Pipeline {
	pipelineStr := "appsink name=appsink"
	pipelineSrc := fmt.Sprintf("shmsrc socket-path=%s is-live=true ! queue ! ", trackKey.shmPath)
	switch trackKey.mimeType {
	case "video/vp8":
		pipelineStr = pipelineSrc + "vp8enc error-resilient=partitions keyframe-max-dist=10 auto-alt-ref=true cpu-used=5 deadline=1 ! " + pipelineStr
	case "video/vp9":
		pipelineStr = pipelineSrc + "vp9parse ! " + pipelineStr
	case "video/h264":
		pipelineStr = pipelineSrc + "h264parse ! " + pipelineStr
	case "audio/opus":
		pipelineStr = pipelineSrc + "opusenc ! " + pipelineStr
	case "audio/pcmu":
		pipelineStr = pipelineSrc + "audio/x-raw, rate=8000 ! mulawenc ! " + pipelineStr
	case "audio/pcma":
		pipelineStr = pipelineSrc + "audio/x-raw, rate=8000 ! alawenc ! " + pipelineStr
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
					panic(err)
				}
			}
			return gst.FlowOK
		},
	})
	return pipeline
}
