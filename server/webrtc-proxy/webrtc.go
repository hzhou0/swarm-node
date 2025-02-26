package main

import (
	"context"
	"errors"
	"fmt"
	"github.com/go-gst/go-glib/glib"
	"github.com/go-gst/go-gst/gst"
	"github.com/go-gst/go-gst/gst/app"
	"github.com/go-resty/resty/v2"
	"github.com/matoous/go-nanoid/v2"
	"github.com/pion/webrtc/v4"
	"github.com/pion/webrtc/v4/pkg/media"
	"google.golang.org/protobuf/proto"
	"iter"
	"log"
	"maps"
	"net/url"
	"os"
	"path"
	"reflect"
	"slices"
	"strings"
	"sync"
	"time"
	"webrtc-proxy/grpc/go"
)

type UUID = string

func NewUUID(len ...int) UUID {
	id, err := gonanoid.New(len...)
	if err != nil {
		panic(err)
	}
	return id
}

type NamedTrackKey struct {
	trackId  string
	streamId string
	mimeType string
}

//func (n NamedTrackKey) shmPath(mediaDir string, sender string) string {
//	if sender == "" {
//		sender = "outbound"
//	}
//
//	serialized := fmt.Sprintf("gst|%s|%s|%s|%s", sender, n.streamId, n.trackId, strings.ToLower(n.mimeType))
//	serialized = strings.ReplaceAll(serialized, "/", "_")
//	return path.Join(mediaDir, serialized)
//}

func (n NamedTrackKey) toProto() *pb.NamedTrack {
	msg := &pb.NamedTrack{}
	msg.SetTrackId(n.trackId)
	msg.SetStreamId(n.streamId)
	msg.SetMimeType(n.mimeType)
	return msg
}

func NamedTrackKeyFromProto(msg *pb.NamedTrack) NamedTrackKey {
	return NewNamedTrackKey(msg.GetTrackId(), msg.GetStreamId(), msg.GetMimeType())
}

func NewNamedTrackKey(trackId string, streamId string, mimeType string) NamedTrackKey {
	return NamedTrackKey{trackId, streamId, strings.ToLower(mimeType)}
}

func MapIter[T, V any](ts iter.Seq[T], fn func(T) V) []V {
	var result []V
	for t := range ts {
		result = append(result, fn(t))
	}
	return result
}

func Map[T, V any](ts []T, fn func(T) V) []V {
	result := make([]V, len(ts))
	for i, t := range ts {
		result[i] = fn(t)
	}
	return result
}

type TrackState struct {
	pipeline    *gst.Pipeline
	subscribers map[*WebrtcPeer]*webrtc.TrackLocalStaticSample
	broadcast   bool
	socket      SocketFilename
}

type WebrtcPeerRole = int

const (
	WebrtcPeerRoleT = iota + 1
	WebrtcPeerRoleB = iota + 1
)

type WebrtcPeer struct {
	pc          *webrtc.PeerConnection
	datachannel *webrtc.DataChannel
	role        WebrtcPeerRole                   // the local role in this relationship
	outTracks   map[NamedTrackKey]SocketFilename // to peer
	inTracks    map[NamedTrackKey]*TrackState    // from peer
	dataOut     chan []byte
	fails       uint
	close       func()
	Fail        func()
	sync.Mutex
}

type SocketFilename = string

type PeeringOffer struct {
	peerId      UUID
	sdp         *webrtc.SessionDescription
	outTracks   map[NamedTrackKey]SocketFilename
	inTracks    []NamedTrackKey
	dataChannel bool
}

func (po *PeeringOffer) Prenegotiate(state *WebrtcState) error {
	// To initiate pre-negotiation, peerId must be a valid URI
	// No other IDs are currently supported
	if _, err := url.ParseRequestURI(po.peerId); err != nil {
		return err
	}
	query := pb.WebrtcOffer{}
	query.SetSrcUuid(state.SrcUUID)
	query.SetLocalTracks(MapIter(maps.Keys(po.outTracks), NamedTrackKey.toProto))
	query.SetLocalTracksSet(true)
	query.SetRemoteTracksSet(false)
	query.SetDatachannel(po.dataChannel)
	payload, err := proto.Marshal(&query)
	if err != nil {
		return err
	}

	state.configMu.RLock()
	resp, err := state.config.client.R().SetHeader("Content-Type", "application/x-protobuf").SetBody(payload).Put(po.peerId)
	state.configMu.RUnlock()
	if err != nil {
		return err
	}
	if resp.StatusCode() < 200 || resp.StatusCode() > 300 {
		return errors.New(fmt.Sprintf("unsuccessful HTTP Status: %d", resp.StatusCode()))
	}
	answer := pb.WebrtcOffer{}
	err = proto.Unmarshal(resp.Body(), &answer)
	if err != nil {
		return err
	}

	if !(answer.HasLocalTracksSet() && answer.HasRemoteTracksSet()) {
		return errors.New("answer does not have local or remote tracks set")
	}
	var allowedRemote []NamedTrackKey
	for _, track := range answer.GetLocalTracks() {
		k := NamedTrackKeyFromProto(track)
		if state.InTrackAllowed(k) {
			allowedRemote = append(allowedRemote, k)
		}
	}
	allowedLocal := make(map[NamedTrackKey]SocketFilename)
	for _, track := range answer.GetRemoteTracks() {
		k := NamedTrackKeyFromProto(track)
		if v, exists := po.outTracks[k]; exists {
			allowedLocal[k] = v
		}
	}
	po.outTracks = allowedLocal
	po.inTracks = allowedRemote
	return nil
}

type WebrtcStateConfig struct {
	webrtcConfig      webrtc.Configuration
	client            *resty.Client
	cloudflareZT      *pb.WebrtcConfig_CloudflareZeroTrust
	reconnectAttempts uint
	allowedInTracks   []NamedTrackKey
}

type WebrtcState struct {
	SrcUUID              UUID
	ServerMediaSocketDir string
	ClientMediaSocketDir string
	config               WebrtcStateConfig
	webrtcApi            *webrtc.API
	configMu             sync.RWMutex
	peers                map[UUID]*WebrtcPeer
	peersMu              sync.RWMutex
	outTrackStates       map[NamedTrackKey]*TrackState
	outTracksMu          sync.RWMutex
	outTracksIdPool      IDPool
	BackgroundChange     chan struct{}
	MediaIn              chan *pb.MediaChannel     // Receive inbound tracks
	DataOut              chan *pb.DataTransmission // Send outbound data
	DataIn               chan *pb.DataTransmission // Receive inbound data
	ctxCancel            context.CancelFunc
	Ctx                  context.Context
}

func NewWebrtcState(config WebrtcStateConfig, ServerMediaSocketDir string, ClientMediaSocketDir string) (*WebrtcState, error) {
	gst.Init(nil)

	err := os.RemoveAll(ServerMediaSocketDir)
	if err != nil {
		return nil, err
	}
	err = os.RemoveAll(ClientMediaSocketDir)
	if err != nil {
		return nil, err
	}

	err = os.MkdirAll(ServerMediaSocketDir, 0750)
	if err != nil {
		return nil, err
	}
	err = os.MkdirAll(ClientMediaSocketDir, 0750)
	if err != nil {
		return nil, err
	}
	mediaEngine := &webrtc.MediaEngine{}
	if err := mediaEngine.RegisterDefaultCodecs(); err != nil {
		return nil, err
	}
	videoRTCPFeedback := []webrtc.RTCPFeedback{{"goog-remb", ""}, {"ccm", "fir"}, {"nack", ""}, {"nack", "pli"}}
	if err := mediaEngine.RegisterCodec(webrtc.RTPCodecParameters{
		RTPCodecCapability: webrtc.RTPCodecCapability{
			MimeType:     webrtc.MimeTypeH265,
			ClockRate:    90000,
			SDPFmtpLine:  "",
			Channels:     0,
			RTCPFeedback: videoRTCPFeedback,
		},
		PayloadType: 126, // Use an unused PayloadType; 126 is often unused but configurable
	}, webrtc.RTPCodecTypeVideo); err != nil {
		return nil, err
	}

	ctx, Close := context.WithCancel(context.Background())
	r := &WebrtcState{
		config:               config,
		webrtcApi:            webrtc.NewAPI(webrtc.WithMediaEngine(mediaEngine)),
		SrcUUID:              NewUUID(),
		ServerMediaSocketDir: ServerMediaSocketDir,
		ClientMediaSocketDir: ClientMediaSocketDir,
		peers:                make(map[UUID]*WebrtcPeer),
		outTrackStates:       make(map[NamedTrackKey]*TrackState),
		outTracksIdPool:      NewIDPool(),
		BackgroundChange:     make(chan struct{}, 1),
		DataOut:              make(chan *pb.DataTransmission, 100),
		DataIn:               make(chan *pb.DataTransmission, 100),
		MediaIn:              make(chan *pb.MediaChannel, 10),
		ctxCancel:            Close,
		Ctx:                  ctx,
	}

	go func() {
		loop := glib.NewMainLoop(glib.MainContextDefault(), true)
		go loop.Run()
		defer loop.Quit()
		for {
			select {
			case <-r.Ctx.Done():
				return
			case dataOut := <-r.DataOut:
				r.peersMu.RLock()
				if peer, exist := r.peers[dataOut.GetChannel().GetDestUuid()]; exist {
					dataBytes := dataOut.GetPayload()
					peer.dataOut <- dataBytes
				} else {
					log.Println("Peer does not exist for data send")
				}
				r.peersMu.RUnlock()
			}
		}
	}()
	return r, nil
}

func (state *WebrtcState) Close() {
	state.ctxCancel()
	for _, peer := range state.peers {
		peer.close()
	}

	state.outTracksMu.Lock()
	defer state.outTracksMu.Unlock()
	for key, outTrack := range state.outTrackStates {
		err := outTrack.pipeline.SetState(gst.StateNull)
		if err != nil {
			log.Printf("Error closing broadcast track %v: %v", key, err)
			continue
		}
		delete(state.outTrackStates, key)
	}
	err := os.RemoveAll(state.ServerMediaSocketDir)
	if err != nil {
		log.Println(err)
	}
	err = os.RemoveAll(state.ClientMediaSocketDir)
	if err != nil {
		log.Println(err)
	}
}

func (state *WebrtcState) Reconfigure(config WebrtcStateConfig) {
	state.configMu.Lock()
	state.config = config
	state.configMu.Unlock()
}

// OutTracks Returns the current outbound track keys
func (state *WebrtcState) OutTracks() []NamedTrackKey {
	state.outTracksMu.RLock()
	defer state.outTracksMu.RUnlock()
	return slices.Collect(maps.Keys(state.outTrackStates))
}

func (state *WebrtcState) BroadcastOutTracks() []NamedTrackKey {
	state.outTracksMu.RLock()
	defer state.outTracksMu.RUnlock()
	ret := make([]NamedTrackKey, 0, 10)
	for key, track := range state.outTrackStates {
		if track.broadcast {
			ret = append(ret, key)
		}
	}
	return ret
}

func (state *WebrtcState) InTrackAllowed(key NamedTrackKey) bool {
	state.configMu.RLock()
	defer state.configMu.RUnlock()
	for _, trackKey := range state.config.allowedInTracks {
		if key.trackId == trackKey.trackId && key.streamId == trackKey.streamId && key.mimeType == trackKey.mimeType {
			return true
		}
	}
	return false
}

// unsafeClose NOT THREADSAFE: closes the peer connection and cleans up associated resources, including tracks and data channels.
func (peer *WebrtcPeer) unsafeClose(peerId string, state *WebrtcState) {
	state.peersMu.Lock()
	delete(state.peers, peerId)
	state.peersMu.Unlock()
	close(peer.dataOut)
	if peer.outTracks != nil {
		state.outTracksMu.Lock()
		for outTrack := range peer.outTracks {
			if ot, exists := state.outTrackStates[outTrack]; exists {
				if !ot.broadcast {
					err := ot.pipeline.SetState(gst.StateNull)
					if err != nil {
						log.Println(err)
					}
					delete(state.outTrackStates, outTrack)
				} else {
					delete(ot.subscribers, peer)
				}
			}
		}
		state.outTracksMu.Unlock()
	}
	peer.outTracks = nil
	if peer.inTracks != nil {
		for trackKey, trackState := range peer.inTracks {
			state.outTracksIdPool.Release(trackState.socket)
			err := trackState.pipeline.SetState(gst.StateNull)
			if err != nil {
				log.Println(err)
			}
			state.MediaIn <- pb.MediaChannel_builder{
				SrcUuid:    proto.String(peerId),
				DestUuid:   nil,
				Track:      trackKey.toProto(),
				SocketName: proto.String(trackState.socket),
				Close:      proto.Bool(true),
			}.Build()
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
	log.Printf("Closed local->%s\n", peerId)
	if _, err := url.ParseRequestURI(peerId); err == nil {
		go func() {
			deletion := pb.WebrtcOffer{}
			deletion.SetSrcUuid(state.SrcUUID)
			body, err := proto.Marshal(&deletion)
			if err != nil {
				panic(err)
			}
			state.configMu.RLock()
			_, err = state.config.client.R().SetBody(body).Delete(peerId)
			state.configMu.RUnlock()
			if err != nil {
				log.Printf("HTTP  unpeer %s: %v\n", peerId, err)
			}
		}()
	}
}

func (peer *WebrtcPeer) setupDataChannel(offer PeeringOffer, state *WebrtcState) {
	peer.datachannel.OnMessage(func(msg webrtc.DataChannelMessage) {
		trans := pb.DataTransmission{}
		dChan := pb.DataChannel{}
		dChan.SetSrcUuid(offer.peerId)
		trans.SetChannel(&dChan)
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
// 2. sdp ==nil: `peerId` must be a POST URL that accepts pb.WebrtcOffer. Assume the T role and nil is returned. `offer.outTracks` and `offer.inTracks` will be modified with Prenegotiate().
// 3. sdp!=nil: `peerId` can be any string. Assume the B role and a webrtc.SessionDescription answer is returned.
func (state *WebrtcState) Peer(offer PeeringOffer, fails uint) (ans *webrtc.SessionDescription, err error) {
	// If peerId is none, create the media pipeline and return
	if offer.peerId == "" {
		state.outTracksMu.Lock()
		for t, p := range offer.outTracks {
			_, exists := state.outTrackStates[t]
			if !exists {
				pipeline := state.outgoingPipeline(t, p)
				state.outTrackStates[t] = &TrackState{subscribers: make(map[*WebrtcPeer]*webrtc.TrackLocalStaticSample), pipeline: pipeline, broadcast: true, socket: p}
			}
		}
		state.outTracksMu.Unlock()
		return nil, nil
	}

	state.peersMu.Lock()
	_, exists := state.peers[offer.peerId]
	if exists {
		state.peersMu.Unlock()
		return nil, errors.New("peer already exists")
	}
	// Create a new peer
	newPeer := &WebrtcPeer{
		inTracks: make(map[NamedTrackKey]*TrackState),
		dataOut:  make(chan []byte, 10),
	}
	newPeer.Lock()
	defer newPeer.Unlock()
	state.peers[offer.peerId] = newPeer
	state.peersMu.Unlock()

	newPeer.fails = fails
	newPeer.close = sync.OnceFunc(func() { newPeer.unsafeClose(offer.peerId, state) })
	newPeer.Fail = sync.OnceFunc(func() {
		log.Printf("Failed -->%s", offer.peerId)
		newPeer.close()
		if newPeer.role == WebrtcPeerRoleT {
			state.configMu.RLock()
			if newPeer.fails < state.config.reconnectAttempts {
				log.Printf("try reconnecting -->%s\n", offer.peerId)
				state.configMu.RUnlock()
				_, err = state.Peer(offer, newPeer.fails+1)
				if err != nil {
					log.Printf("reconnection failed -->%s %v\n", offer.peerId, err)
				}
			} else {
				state.configMu.RUnlock()
				select {
				case state.BackgroundChange <- struct{}{}:
				default:
				}
			}
		}
	})
	defer func() {
		if err != nil {
			log.Printf("Peering failed: %v\n", err)
			newPeer.Fail()
		}
	}()
	state.configMu.RLock()
	newPeer.pc, err = state.webrtcApi.NewPeerConnection(state.config.webrtcConfig)
	if err != nil {
		return nil, err
	}
	state.configMu.RUnlock()

	if offer.sdp != nil {
		newPeer.role = WebrtcPeerRoleB
	} else {
		newPeer.role = WebrtcPeerRoleT
		err = offer.Prenegotiate(state)
		if err != nil {
			return nil, err
		}
	}

	newPeer.outTracks = offer.outTracks
	for v, socket := range offer.outTracks {
		var webrtcTrack *webrtc.TrackLocalStaticSample
		webrtcTrack, err = webrtc.NewTrackLocalStaticSample(webrtc.RTPCodecCapability{MimeType: v.mimeType}, v.trackId, v.streamId)
		if err != nil {
			return nil, err
		} else if _, err = newPeer.pc.AddTrack(webrtcTrack); err != nil {
			return nil, err
		}
		state.outTracksMu.Lock()
		namedTrack, exists := state.outTrackStates[v]
		if !exists {
			pipeline := state.outgoingPipeline(v, socket)
			namedTrack = &TrackState{subscribers: make(map[*WebrtcPeer]*webrtc.TrackLocalStaticSample), pipeline: pipeline, broadcast: false, socket: socket}
			state.outTrackStates[v] = namedTrack
		}
		namedTrack.subscribers[newPeer] = webrtcTrack
		state.outTracksMu.Unlock()
	}

	newPeer.incomingPipeline(state, offer.peerId)

	newPeer.pc.OnICEConnectionStateChange(func(s webrtc.ICEConnectionState) {
		log.Printf("ICE %s %s->%s\n", strings.ToUpper(s.String()), state.SrcUUID, offer.peerId)
		switch s {
		case webrtc.ICEConnectionStateConnected:
			newPeer.Lock()
			for t := range newPeer.outTracks {
				if err = state.outTrackStates[t].pipeline.Start(); err != nil {
					log.Println(err)
					go newPeer.Fail()
					return
				}
			}
			newPeer.Unlock()
		case webrtc.ICEConnectionStateCompleted:
			newPeer.Lock()
			newPeer.fails = 0
			newPeer.Unlock()
		case webrtc.ICEConnectionStateClosed:
			go newPeer.Fail()
		case webrtc.ICEConnectionStateFailed:
			go newPeer.Fail()
		default:
		}
	})

	if offer.dataChannel {
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
				newPeer.Fail()
				return nil, err
			}
			newPeer.setupDataChannel(offer, state)
		}
	}

	// Perform SDP Exchange
	if newPeer.role == WebrtcPeerRoleB {
		err = newPeer.pc.SetRemoteDescription(*offer.sdp)
		if err != nil {
			newPeer.Fail()
			return nil, err
		}

		var answer webrtc.SessionDescription
		answer, err = newPeer.pc.CreateAnswer(nil)
		if err != nil {
			newPeer.Fail()
			return nil, err
		}

		// Create channel that is blocked until ICE Gathering is complete
		gatherComplete := webrtc.GatheringCompletePromise(newPeer.pc)

		// Sets the LocalDescription, and starts our UDP listeners
		err = newPeer.pc.SetLocalDescription(answer)
		if err != nil {
			newPeer.Fail()
			return nil, err
		}

		<-gatherComplete

		return newPeer.pc.LocalDescription(), nil
	} else if newPeer.role == WebrtcPeerRoleT {
		// For outgoing requests, peerId must be a valid URI
		// No other IDs are currently supported
		// This must be at step 3: both local_tracks and remote_tracks must be wanted
		if _, err = url.ParseRequestURI(offer.peerId); err != nil {
			return nil, err
		}

		var sdpOffer webrtc.SessionDescription
		sdpOffer, err = newPeer.pc.CreateOffer(nil)
		if err != nil {
			return nil, err
		}

		// Create channel that is blocked until ICE Gathering is complete
		gatherComplete := webrtc.GatheringCompletePromise(newPeer.pc)

		// Sets the LocalDescription, and starts our UDP listeners
		if err = newPeer.pc.SetLocalDescription(sdpOffer); err != nil {
			return nil, err
		}
		<-gatherComplete

		newOffer := pb.WebrtcOffer{}
		newOffer.SetSrcUuid(state.SrcUUID)
		localSDPOffer := newPeer.pc.LocalDescription()
		newOffer.SetSdp(localSDPOffer.SDP)
		newOffer.SetType(localSDPOffer.Type.String())
		newOffer.SetLocalTracks(MapIter(maps.Keys(offer.outTracks), NamedTrackKey.toProto))
		newOffer.SetLocalTracksSet(true)
		newOffer.SetRemoteTracks(Map(offer.inTracks, NamedTrackKey.toProto))
		newOffer.SetRemoteTracksSet(true)
		newOffer.SetDatachannel(offer.dataChannel)
		var payload []byte
		payload, err = proto.Marshal(&newOffer)
		if err != nil {
			return nil, err
		}
		// Set the remote SessionDescription when received
		var resp *resty.Response
		state.configMu.RLock()
		resp, err = state.config.client.R().SetHeader("Content-Type", "application/x-protobuf").SetBody(payload).Put(offer.peerId)
		state.configMu.RUnlock()
		if err != nil {
			return nil, err
		}
		if resp.StatusCode() < 200 || resp.StatusCode() > 300 {
			err = errors.New(fmt.Sprintf("Unsuccessful HTTP Status: %d", resp.StatusCode()))
			return nil, err
		}
		answer := pb.WebrtcOffer{}
		err = proto.Unmarshal(resp.Body(), &answer)
		if err != nil {
			return nil, err
		}
		answerSdp := webrtc.SessionDescription{
			Type: webrtc.NewSDPType(answer.GetType()),
			SDP:  answer.GetSdp(),
		}
		err = newPeer.pc.SetRemoteDescription(answerSdp)
		if err != nil {
			return nil, err
		}
	} else {
		panic("impossible")
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
	peer.close()
}

func (peer *WebrtcPeer) incomingPipeline(state *WebrtcState, peerId UUID) {
	peer.pc.OnTrack(func(track *webrtc.TrackRemote, rtpReceiver *webrtc.RTPReceiver) {
		peer.Lock()
		defer peer.Unlock()
		trackKey := NewNamedTrackKey(track.ID(), track.StreamID(), track.Codec().MimeType)
		if !state.InTrackAllowed(trackKey) {
			log.Printf("Disallowed track %+v, closing connection\n", trackKey)
			err := peer.pc.Close()
			if err != nil {
				panic(err)
			}
			return
		}
		log.Printf("Track has started, of type %d: %s \n", track.PayloadType(), track.Codec().MimeType)

		pipelineString := "appsrc format=time is-live=true name=src ! application/x-rtp"
		switch strings.ToLower(track.Codec().MimeType) {
		case "video/vp8":
			pipelineString += fmt.Sprintf(", payload=%d, encoding-name=VP8-DRAFT-IETF-01 ! rtpvp8depay ! ", track.PayloadType())
		case "video/opus":
			pipelineString += fmt.Sprintf(", payload=%d, encoding-name=OPUS ! rtpopusdepay ! ", track.PayloadType())
		case "video/vp9":
			pipelineString += " ! "
		case "video/h264":
			pipelineString += " ! rtpjitterbuffer drop-on-latency=true latency=400 ! rtph264depay ! video/x-h264,stream-format=byte-stream,alignment=au ! "
		case "video/h265":
			pipelineString += " ! rtpjitterbuffer drop-on-latency=true latency=400 ! rtph265depay ! video/x-h265,stream-format=byte-stream,alignment=au ! "
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
		trackSocketName := state.outTracksIdPool.Claim()
		sinkString := fmt.Sprintf("shmsink socket-path=%s wait-for-connection=true shm-size=671088640", path.Join(state.ServerMediaSocketDir, trackSocketName))
		pipelineString += sinkString
		pipeline, err := gst.NewPipelineFromString(pipelineString)
		if err != nil {
			panic(err)

		}
		appEle, err := pipeline.GetElementByName("src")
		if err != nil {
			panic(err)
		}
		appSrc := app.SrcFromElement(appEle)
		if err = pipeline.Start(); err != nil {
			panic(err)
		}

		if _, t := peer.inTracks[trackKey]; t {
			panic("track already exists")
		}
		peer.inTracks[trackKey] = &TrackState{pipeline: pipeline, socket: trackSocketName}

		state.MediaIn <- pb.MediaChannel_builder{
			SrcUuid:    proto.String(peerId),
			DestUuid:   nil,
			Track:      trackKey.toProto(),
			SocketName: proto.String(trackSocketName),
			Close:      nil,
		}.Build()

		buf := make([]byte, 1500)
		for {
			i, _, readErr := track.Read(buf)
			if readErr != nil {
				log.Printf("Error reading track: %v, closing connection\n", readErr)
				go peer.Fail()
				break
			}
			gstBuffer := gst.NewBufferFromBytes(buf[:i])
			appSrc.PushBuffer(gstBuffer)
		}
	})
}

func (state *WebrtcState) outgoingPipeline(trackKey NamedTrackKey, socketFile SocketFilename) *gst.Pipeline {
	pipelineStr := "appsink name=appsink"
	pipelineSrc := fmt.Sprintf("shmsrc socket-path=%s is-live=true ! ", path.Join(state.ClientMediaSocketDir, socketFile))
	switch strings.ToLower(trackKey.mimeType) {
	case "video/vp8":
		pipelineStr = pipelineSrc + "vp8enc error-resilient=partitions keyframe-max-dist=10 auto-alt-ref=true cpu-used=5 deadline=1 ! " + pipelineStr
	case "video/vp9":
		pipelineStr = pipelineSrc + "vp9parse ! " + pipelineStr
	case "video/h264":
		pipelineStr = pipelineSrc + "video/x-h264,stream-format=byte-stream,alignment=au ! " + pipelineStr
	case "video/h265":
		pipelineStr = pipelineSrc + "video/x-h265,stream-format=byte-stream,alignment=au ! " + pipelineStr
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
			state.outTracksMu.RLock()
			defer state.outTracksMu.RUnlock()
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
			var mediaSample media.Sample
			if buffer.Duration() == gst.ClockTimeNone {
				mediaSample = media.Sample{Data: samples, Timestamp: time.Now()}
			} else {
				mediaSample = media.Sample{Data: samples, Duration: *buffer.Duration().AsDuration()}
			}
			for _, webrtcTrack := range namedTrackVal.subscribers {
				if err := webrtcTrack.WriteSample(mediaSample); err != nil {
					return gst.FlowError
				}
			}
			return gst.FlowOK
		},
	})

	pipeline.GetBus().AddWatch(func(msg *gst.Message) bool {
		switch msg.Type() {
		case gst.MessageEOS:
			fallthrough
		case gst.MessageError:
			err := msg.ParseError()
			log.Printf("Pipeline error (%v): %s, Debug info: %s\n", err.Code(), err.Message(), err.DebugString())
			state.outTracksMu.Lock()
			if track, exists := state.outTrackStates[trackKey]; exists {
				err := track.pipeline.SetState(gst.StateNull)
				if err != nil {
					log.Println(err)
				}
				delete(state.outTrackStates, trackKey)
				state.outTracksMu.Unlock()
				for peer := range track.subscribers {
					go peer.Fail()
				}
			}
			return false
		}
		return true
	})
	return pipeline
}

func (state *WebrtcState) Reconcile(stateMsg *pb.State) error {
	if err := state.Ctx.Err(); err != nil {
		return fmt.Errorf("webrtc closed %w", err)
	}
	state.configMu.RLock()
	if stateMsg.HasReconnectAttempts() {
		state.config.reconnectAttempts = uint(stateMsg.GetReconnectAttempts())
	}
	if stateMsg.HasConfig() {
		state.config.webrtcConfig = webrtc.Configuration{
			ICEServers: Map(stateMsg.GetConfig().GetIceServers(), func(s *pb.WebrtcConfig_IceServer) webrtc.ICEServer {
				var credType webrtc.ICECredentialType
				switch s.GetCredentialType() {
				case "password":
					credType = webrtc.ICECredentialTypePassword
				case "oauth":
					credType = webrtc.ICECredentialTypeOauth
				default:
					credType = webrtc.ICECredentialTypePassword
				}
				return webrtc.ICEServer{
					URLs:           s.GetUrls(),
					Username:       s.GetUsername(),
					Credential:     s.GetCredential(),
					CredentialType: credType,
				}
			}),
		}
		switch stateMsg.GetConfig().WhichAuth() {
		case pb.WebrtcConfig_Auth_not_set_case:
			state.config.client = resty.New()
			state.config.cloudflareZT = nil
		case pb.WebrtcConfig_CloudflareAuth_case:
			cf := stateMsg.GetConfig().GetCloudflareAuth()
			if !cf.HasClientSecret() || !cf.HasClientId() {
				return errors.New("cloudflare auth requires client secret and client id")
			}
			state.config.client = resty.New().SetHeaders(map[string]string{
				"CF-Access-Client-Id":     cf.GetClientId(),
				"CF-Access-Client-Secret": cf.GetClientSecret(),
			})
			state.config.cloudflareZT = cf
		}
	}
	state.config.allowedInTracks = Map(stateMsg.GetWantedTracks(), NamedTrackKeyFromProto)
	state.configMu.RUnlock()

	// Find desired the desired state for each peer, represented by a peeringOffer
	peeringOffers := make(map[UUID]PeeringOffer)
	for _, dataChan := range stateMsg.GetData() {
		peer := dataChan.GetDestUuid()
		po := peeringOffers[peer]
		po.dataChannel = true
		peeringOffers[peer] = po
	}
	for _, mediaChan := range stateMsg.GetMedia() {
		peer := mediaChan.GetDestUuid()
		po := peeringOffers[peer]
		ntk := NamedTrackKeyFromProto(mediaChan.GetTrack())
		if po.outTracks == nil {
			po.outTracks = make(map[NamedTrackKey]SocketFilename)
		}
		po.outTracks[ntk] = mediaChan.GetSocketName()
		peeringOffers[peer] = po
	}

	var peersToCreate []UUID
	var peersToModify []UUID
	var peersToClose []UUID
	state.peersMu.RLock()
	for uuid, peer := range state.peers {
		if target, offerExists := peeringOffers[uuid]; offerExists {
			hasData := peer.dataOut != nil
			peer.Lock()
			if target.dataChannel != hasData || !reflect.DeepEqual(target.outTracks, peer.outTracks) {
				peersToModify = append(peersToModify, uuid)
			}
			peer.Unlock()
		} else {
			peersToClose = append(peersToClose, uuid)
		}
	}
	for uuid := range peeringOffers {
		if _, peerExists := state.peers[uuid]; !peerExists {
			peersToCreate = append(peersToCreate, uuid)
		}
	}
	state.peersMu.RUnlock()

	var wg sync.WaitGroup
	for _, modPeer := range peersToModify {
		wg.Add(1)
		pf := peeringOffers[modPeer]
		pf.peerId = modPeer
		go func() {
			defer wg.Done()
			state.UnPeer(modPeer)
			_, err := state.Peer(pf, 0)
			if err != nil {
				log.Printf("Failed to re-peer %s\n", err)
			}
		}()
	}
	for _, createPeer := range peersToCreate {
		wg.Add(1)
		pf := peeringOffers[createPeer]
		pf.peerId = createPeer
		go func() {
			defer wg.Done()
			_, err := state.Peer(pf, 0)
			if err != nil {
				log.Printf("Failed to peer %s\n", err)
			}
		}()
	}
	for _, closePeer := range peersToClose {
		wg.Add(1)
		go func() {
			defer wg.Done()
			state.UnPeer(closePeer)
		}()
	}
	wg.Wait()
	return nil
}

func (state *WebrtcState) ToProto(httpServer *WebrtcHttpInterfaceState) (*pb.State, error) {
	if err := state.Ctx.Err(); err != nil {
		return nil, fmt.Errorf("webrtc closed %w", err)
	}
	state.peersMu.RLock()
	dataChannels := make([]*pb.DataChannel, 0)
	mediaChannels := make([]*pb.MediaChannel, 0)
	for uuid, peer := range state.peers {
		peer.Lock()
		if peer.datachannel != nil {
			d := &pb.DataChannel{}
			d.SetDestUuid(uuid)
			dataChannels = append(dataChannels, d)
		}
		for key, socketName := range peer.outTracks {
			m := pb.MediaChannel_builder{
				SrcUuid:    nil,
				DestUuid:   proto.String(uuid),
				Track:      key.toProto(),
				SocketName: proto.String(socketName),
				Close:      nil,
			}.Build()
			mediaChannels = append(mediaChannels, m)
		}
		peer.Unlock()
	}
	state.peersMu.RUnlock()

	state.configMu.RLock()
	iceServers := Map(state.config.webrtcConfig.ICEServers, func(s webrtc.ICEServer) *pb.WebrtcConfig_IceServer {
		r := &pb.WebrtcConfig_IceServer{}
		r.SetUrls(s.URLs)
		r.SetCredential(fmt.Sprintf("%v", s.Credential))
		r.SetUsername(s.Username)
		r.SetCredentialType(s.CredentialType.String())
		return r
	})
	msg := pb.State_builder{
		Data:              dataChannels,
		Media:             mediaChannels,
		WantedTracks:      Map(state.config.allowedInTracks, NamedTrackKey.toProto),
		Config:            pb.WebrtcConfig_builder{IceServers: iceServers, CloudflareAuth: state.config.cloudflareZT}.Build(),
		ReconnectAttempts: proto.Uint32(uint32(state.config.reconnectAttempts)),
		HttpServerConfig:  nil,
	}
	state.configMu.RUnlock()

	httpServer.serverMu.Lock()
	msg.HttpServerConfig = httpServer.serverConfig
	httpServer.serverMu.Unlock()

	return msg.Build(), nil
}
