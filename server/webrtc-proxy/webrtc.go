package main

import (
	"context"
	"errors"
	"fmt"
	"github.com/cretz/bine/tor"
	"github.com/go-gst/go-glib/glib"
	"github.com/go-gst/go-gst/gst"
	"github.com/go-gst/go-gst/gst/app"
	"github.com/go-resty/resty/v2"
	"github.com/matoous/go-nanoid/v2"
	"github.com/pion/webrtc/v4"
	"google.golang.org/protobuf/proto"
	"iter"
	"log"
	"maps"
	"net/http"
	"net/url"
	"os"
	"reflect"
	"slices"
	"strings"
	"sync"
	"time"
	"webrtc-proxy/grpc/go"
)

type TorClient struct {
	transport *http.Transport
	tor       *tor.Tor
}

func NewTorClient() (*TorClient, error) {
	// Start a new Tor instance
	t, err := tor.Start(context.Background(), &tor.StartConf{
		TempDataDirBase: os.TempDir(),
		EnableNetwork:   true,
	})

	if err != nil {
		return nil, err
	}

	// Create a SOCKS5 dialer for the Tor instance
	dialCtx, dialCancel := context.WithTimeout(context.Background(), time.Minute)
	defer dialCancel()
	dialer, err := t.Dialer(dialCtx, nil)
	if err != nil {
		return nil, err
	}

	transport := &http.Transport{
		// Use SOCKS5 proxy dialer to route all traffic through Tor
		DialContext: dialer.DialContext,
	}
	return &TorClient{
		transport: transport,
		tor:       t,
	}, nil
}

var torClient *TorClient = nil
var torClientMu sync.Mutex

func LoadTorClient() *TorClient {
	torClientMu.Lock()
	defer torClientMu.Unlock()
	if torClient != nil {
		return torClient
	}
	var err error
	torClient, err = NewTorClient()
	if err != nil {
		panic(err)
	}
	return torClient
}

func DestroyTorClient() {
	torClientMu.Lock()
	defer torClientMu.Unlock()
	if torClient != nil {
		_ = torClient.tor.Close()
		torClient = nil
	}
}

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
	subscribers map[*WebrtcPeer]*webrtc.TrackLocalStaticRTP
	broadcast   bool
	port        LocalhostPort
}

type WebrtcPeerRole = int

const (
	WebrtcPeerRoleT = iota + 1
	WebrtcPeerRoleB = iota + 1
)

type WebrtcPeer struct {
	client      *resty.Client
	pc          *webrtc.PeerConnection
	datachannel *webrtc.DataChannel
	role        WebrtcPeerRole                  // the local role in this relationship
	outTracks   map[NamedTrackKey]LocalhostPort // to peer
	inTracks    map[NamedTrackKey]*TrackState   // from peer
	dataOut     chan []byte
	fails       uint
	close       func()
	Fail        func()
	sync.Mutex
}

type LocalhostPort = uint32

type PeeringOffer struct {
	peerId      UUID
	sdp         *webrtc.SessionDescription
	outTracks   map[NamedTrackKey]LocalhostPort
	inTracks    []NamedTrackKey
	dataChannel bool
}

func (po *PeeringOffer) Prenegotiate(state *WebrtcState, client *resty.Client) error {
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
	resp, err := client.R().SetHeader("Content-Type", "application/x-protobuf").SetBody(payload).Put(po.peerId)
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
		if allowed, _ := state.InTrackAllowed(k); allowed {
			allowedRemote = append(allowedRemote, k)
		}
	}
	allowedLocal := make(map[NamedTrackKey]LocalhostPort)
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
	credentials       map[UUID]*pb.WebrtcConfigAuth
	reconnectAttempts uint
	allowedInTracks   map[NamedTrackKey]LocalhostPort
}

type WebrtcState struct {
	SrcUUID          UUID
	config           WebrtcStateConfig
	webrtcApi        *webrtc.API
	configMu         sync.RWMutex
	peers            map[UUID]*WebrtcPeer
	peersMu          sync.RWMutex
	outTrackStates   map[NamedTrackKey]*TrackState
	outTracksMu      sync.RWMutex
	BackgroundChange chan struct{}
	MediaIn          chan *pb.MediaChannel     // Receive inbound tracks
	DataOut          chan *pb.DataTransmission // Send outbound data
	DataIn           chan *pb.DataTransmission // Receive inbound data
	StatsOut         chan []*pb.Stats
	ctxCancel        context.CancelFunc
	Ctx              context.Context
}

func NewWebrtcState(config WebrtcStateConfig) (*WebrtcState, error) {
	gst.Init(nil)

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
		config:           config,
		webrtcApi:        webrtc.NewAPI(webrtc.WithMediaEngine(mediaEngine)),
		SrcUUID:          NewUUID(),
		peers:            make(map[UUID]*WebrtcPeer),
		outTrackStates:   make(map[NamedTrackKey]*TrackState),
		BackgroundChange: make(chan struct{}, 1),
		DataOut:          make(chan *pb.DataTransmission, 100),
		DataIn:           make(chan *pb.DataTransmission, 100),
		StatsOut:         make(chan []*pb.Stats, 1),
		MediaIn:          make(chan *pb.MediaChannel, 10),
		ctxCancel:        Close,
		Ctx:              ctx,
	}

	go func() {
		loop := glib.NewMainLoop(glib.MainContextDefault(), true)
		go loop.Run()
		defer loop.Quit()
		statsTicker := time.NewTicker(5 * time.Second)
		defer statsTicker.Stop()
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
			case <-statsTicker.C:
				log.Printf("starting send stats %s\n", r.SrcUUID)
				r.peersMu.RLock()
				var stats []*pb.Stats
				for destUuid, peer := range r.peers {
					peer.Lock()
					activeCandidateId := ""
					peerStats := pb.Stats{}
				statIter:
					for _, t := range peer.pc.GetStats() {
						switch stat := t.(type) {
						case webrtc.ICECandidatePairStats:
							if stat.Nominated {
								activeCandidateId = stat.RemoteCandidateID
								peerStats.SetDestUuid(destUuid)
								peerStats.SetCumulativeRtt(stat.TotalRoundTripTime)
								peerStats.SetCurrentRtt(stat.CurrentRoundTripTime)
								peerStats.SetOutgoingBitrate(stat.AvailableOutgoingBitrate)
								peerStats.SetIncomingBitrate(stat.AvailableIncomingBitrate)
								break statIter
							}
						}
					}
				statIter2:
					for _, t := range peer.pc.GetStats() {
						switch stat := t.(type) {
						case webrtc.ICECandidateStats:
							if stat.Type == webrtc.StatsTypeRemoteCandidate && stat.ID == activeCandidateId {
								peerStats.SetProtocol(stat.Protocol)
								switch stat.CandidateType {
								case webrtc.ICECandidateTypeUnknown:
									peerStats.SetType(pb.Stats_Unknown)
								case webrtc.ICECandidateTypeHost:
									peerStats.SetType(pb.Stats_Host)
								case webrtc.ICECandidateTypeSrflx:
									peerStats.SetType(pb.Stats_Srflx)
								case webrtc.ICECandidateTypePrflx:
									peerStats.SetType(pb.Stats_Prflx)
								case webrtc.ICECandidateTypeRelay:
									peerStats.SetType(pb.Stats_Relay)
								}
								break statIter2
							}
						}
					}
					peer.Unlock()
					if peerStats.HasDestUuid() {
						stats = append(stats, &peerStats)
					}
				}
				r.peersMu.RUnlock()
				log.Printf("Sending stats %s\n", r.SrcUUID)
				select {
				case r.StatsOut <- stats:
				default:
				}
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

func (state *WebrtcState) InTrackAllowed(key NamedTrackKey) (bool, LocalhostPort) {
	state.configMu.RLock()
	defer state.configMu.RUnlock()
	for trackKey, port := range state.config.allowedInTracks {
		if key.trackId == trackKey.trackId && key.streamId == trackKey.streamId && key.mimeType == trackKey.mimeType {
			return true, port
		}
	}
	return false, 0
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
			err := trackState.pipeline.SetState(gst.StateNull)
			if err != nil {
				log.Println(err)
			}
			state.MediaIn <- pb.MediaChannel_builder{
				SrcUuid:       proto.String(peerId),
				DestUuid:      nil,
				Track:         trackKey.toProto(),
				LocalhostPort: proto.Uint32(trackState.port),
				Close:         proto.Bool(true),
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
			_, err = peer.client.R().SetBody(body).Delete(peerId)
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
				state.outTrackStates[t] = &TrackState{subscribers: make(map[*WebrtcPeer]*webrtc.TrackLocalStaticRTP), pipeline: pipeline, broadcast: true, port: p}
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
	creds, exists := state.config.credentials[offer.peerId]
	if !exists {
		newPeer.client = resty.New()
	} else {
		switch creds.WhichAuth() {
		case pb.WebrtcConfigAuth_Auth_not_set_case:
			newPeer.client = resty.New()
		case pb.WebrtcConfigAuth_CloudflareAuth_case:
			cf := creds.GetCloudflareAuth()
			newPeer.client = resty.New().SetHeaders(map[string]string{
				"CF-Access-Client-Id":     cf.GetClientId(),
				"CF-Access-Client-Secret": cf.GetClientSecret(),
			})
		case pb.WebrtcConfigAuth_OnionServiceV3Auth_case:
			torClient := LoadTorClient()
			newPeer.client = resty.New().SetTransport(torClient.transport).SetTimeout(30 * time.Second)
		}
	}
	newPeer.pc, err = state.webrtcApi.NewPeerConnection(state.config.webrtcConfig)
	if err != nil {
		return nil, err
	}
	state.configMu.RUnlock()

	if offer.sdp != nil {
		newPeer.role = WebrtcPeerRoleB
	} else {
		newPeer.role = WebrtcPeerRoleT
		err = offer.Prenegotiate(state, newPeer.client)
		if err != nil {
			return nil, err
		}
	}

	newPeer.outTracks = offer.outTracks
	for v, socket := range offer.outTracks {
		var webrtcTrack *webrtc.TrackLocalStaticRTP
		webrtcTrack, err = webrtc.NewTrackLocalStaticRTP(webrtc.RTPCodecCapability{MimeType: v.mimeType}, v.trackId, v.streamId)
		if err != nil {
			return nil, err
		} else if _, err = newPeer.pc.AddTrack(webrtcTrack); err != nil {
			return nil, err
		}
		state.outTracksMu.Lock()
		namedTrack, exists := state.outTrackStates[v]
		if !exists {
			pipeline := state.outgoingPipeline(v, socket)
			namedTrack = &TrackState{subscribers: make(map[*WebrtcPeer]*webrtc.TrackLocalStaticRTP), pipeline: pipeline, broadcast: false, port: socket}
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
		resp, err = newPeer.client.R().SetHeader("Content-Type", "application/x-protobuf").SetBody(payload).Put(offer.peerId)
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
		allowed, port := state.InTrackAllowed(trackKey)
		if !allowed {
			log.Printf("Disallowed track %+v, closing connection\n", trackKey)
			peer.Fail()
			return
		}
		pipelineString := fmt.Sprintf("appsrc format=time is-live=true name=src ! application/x-rtp ! udpsink host=localhost port=%d", port)
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
		} else {
			log.Printf("Track has started, of type %d: %s \n", track.PayloadType(), track.Codec().MimeType)
		}

		if _, t := peer.inTracks[trackKey]; t {
			panic("track already exists")
		}
		peer.inTracks[trackKey] = &TrackState{pipeline: pipeline, port: port}

		state.MediaIn <- pb.MediaChannel_builder{
			SrcUuid:       proto.String(peerId),
			DestUuid:      nil,
			Track:         trackKey.toProto(),
			LocalhostPort: proto.Uint32(port),
			Close:         nil,
		}.Build()

		go func() {
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
		}()
	})
}

func (state *WebrtcState) outgoingPipeline(trackKey NamedTrackKey, port LocalhostPort) *gst.Pipeline {
	pipelineStr := fmt.Sprintf("udpsrc address=localhost port=%d ! queue ! appsink name=appsink", port)

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
			bytes := buffer.Map(gst.MapRead).Bytes()
			defer buffer.Unmap()
			for _, webrtcTrack := range namedTrackVal.subscribers {
				if _, err := webrtcTrack.Write(bytes); err != nil {
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
		state.config.credentials = stateMsg.GetConfig().GetCredentials()
	}
	allowedInTracks := make(map[NamedTrackKey]LocalhostPort)
	for _, channel := range stateMsg.GetWantedTracks() {
		allowedInTracks[NamedTrackKeyFromProto(channel.GetTrack())] = channel.GetLocalhostPort()
	}
	state.config.allowedInTracks = allowedInTracks
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
			po.outTracks = make(map[NamedTrackKey]LocalhostPort)
		}
		po.outTracks[ntk] = mediaChan.GetLocalhostPort()
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

func (state *WebrtcState) ToProto(httpServer *WebrtcInterfaceHttp) (*pb.State, error) {
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
		for key, port := range peer.outTracks {
			m := pb.MediaChannel_builder{
				SrcUuid:       nil,
				DestUuid:      proto.String(uuid),
				Track:         key.toProto(),
				LocalhostPort: proto.Uint32(port),
				Close:         nil,
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
	wantedTracks := make([]*pb.MediaChannel, 0)
	for key, port := range state.config.allowedInTracks {
		m := pb.MediaChannel_builder{
			SrcUuid:       nil,
			DestUuid:      nil,
			Track:         key.toProto(),
			LocalhostPort: proto.Uint32(port),
			Close:         nil,
		}.Build()
		wantedTracks = append(wantedTracks, m)
	}
	msg := pb.State_builder{
		Data:              dataChannels,
		Media:             mediaChannels,
		WantedTracks:      wantedTracks,
		Config:            pb.WebrtcConfig_builder{IceServers: iceServers, Credentials: state.config.credentials}.Build(),
		ReconnectAttempts: proto.Uint32(uint32(state.config.reconnectAttempts)),
		HttpServerConfig:  httpServer.Config(),
	}.Build()
	state.configMu.RUnlock()

	return msg, nil
}
