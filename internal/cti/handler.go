package cti

import (
	"context"
	"encoding/json"
	"net/http"
	"sync"
	"time"

	"github.com/gorilla/websocket"
	"go.uber.org/zap"

	"telco-cti-service/internal/crm"
)

type ScreenPop struct {
	CallID      string            `json:"call_id"`
	CallerID    string            `json:"caller_id"`
	Customer    *crm.CustomerInfo `json:"customer"`
	EstWaitSecs int               `json:"estimated_wait_seconds"`
	QueueID     string            `json:"queue_id"`
	Timestamp   time.Time         `json:"timestamp"`
}

type AgentNotification struct {
	Type    string `json:"type"` 
	Payload any    `json:"payload"`
}

type agentConn struct {
	agentID string
	conn    *websocket.Conn
	send    chan []byte
}

type Hub struct {
	agents   map[string]*agentConn
	mu       sync.RWMutex
	upgrader websocket.Upgrader
	log      *zap.Logger
}

func NewHub(log *zap.Logger) *Hub {
	return &Hub{
		agents: make(map[string]*agentConn),
		upgrader: websocket.Upgrader{
			ReadBufferSize:  1024,
			WriteBufferSize: 4096,
			CheckOrigin:     func(r *http.Request) bool { return true },
		},
		log: log,
	}
}

func (h *Hub) Register(agentID string, conn *websocket.Conn) {
	ac := &agentConn{agentID: agentID, conn: conn, send: make(chan []byte, 64)}
	h.mu.Lock()
	h.agents[agentID] = ac
	h.mu.Unlock()
	h.log.Info("agent.connected", zap.String("agent_id", agentID))
	go h.writePump(ac)
	h.readPump(ac) 
}

func (h *Hub) readPump(ac *agentConn) {
	defer func() {
		h.mu.Lock()
		delete(h.agents, ac.agentID)
		h.mu.Unlock()
		ac.conn.Close()
		h.log.Info("agent.disconnected", zap.String("agent_id", ac.agentID))
	}()
	ac.conn.SetReadLimit(512)
	for {
		_, _, err := ac.conn.ReadMessage()
		if err != nil {
			break
		}
	}
}

func (h *Hub) writePump(ac *agentConn) {
	for msg := range ac.send {
		if err := ac.conn.WriteMessage(websocket.TextMessage, msg); err != nil {
			break
		}
	}
}

func (h *Hub) Notify(agentID string, n AgentNotification) {
	h.mu.RLock()
	ac, ok := h.agents[agentID]
	h.mu.RUnlock()
	if !ok {
		h.log.Warn("agent.not_connected", zap.String("agent_id", agentID))
		return
	}
	data, _ := json.Marshal(n)
	select {
	case ac.send <- data:
	default:
		h.log.Warn("agent.send_buffer_full", zap.String("agent_id", agentID))
	}
}

func (h *Hub) Broadcast(n AgentNotification) {
	data, _ := json.Marshal(n)
	h.mu.RLock()
	defer h.mu.RUnlock()
	for _, ac := range h.agents {
		select {
		case ac.send <- data:
		default:
		}
	}
}

type Handler struct {
	hub *Hub
	crm *crm.Client
	log *zap.Logger
}

func NewHandler(hub *Hub, crmClient *crm.Client, log *zap.Logger) *Handler {
	return &Handler{hub: hub, crm: crmClient, log: log}
}

func (h *Handler) HandleIncomingCall(ctx context.Context, callID, callerID, agentID, queueID string) {
	customer, err := h.crm.LookupByPhone(ctx, callerID)
	if err != nil {
		h.log.Error("crm.lookup.error", zap.Error(err))
		customer = &crm.CustomerInfo{Phone: callerID}
	}

	pop := ScreenPop{
		CallID:    callID,
		CallerID:  callerID,
		Customer:  customer,
		QueueID:   queueID,
		Timestamp: time.Now(),
	}
	h.hub.Notify(agentID, AgentNotification{Type: "screen_pop", Payload: pop})
	h.log.Info("screen_pop.sent", zap.String("agent_id", agentID), zap.String("call_id", callID))
}

func (h *Handler) HandleCallEnd(agentID, callID, cause string) {
	h.hub.Notify(agentID, AgentNotification{
		Type:    "call_end",
		Payload: map[string]string{"call_id": callID, "hangup_cause": cause},
	})
}
