package main

import (
	"context"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"go.uber.org/zap"

	"telco-cti-service/internal/crm"
	"telco-cti-service/internal/cti"
)

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func main() {
	log, _ := zap.NewProduction()
	defer log.Sync()

	crmClient := crm.NewClient(
		getEnv("CRM_BASE_URL", "http://crm:8000"),
		getEnv("CRM_API_KEY", ""),
		log,
	)

	hub := cti.NewHub(log)
	handler := cti.NewHandler(hub, crmClient, log)

	upgrader := websocket.Upgrader{
		ReadBufferSize:  1024,
		WriteBufferSize: 4096,
		CheckOrigin:     func(r *http.Request) bool { return true },
	}

	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Recovery())

	r.GET("/healthz", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": "ok"})
	})
	r.GET("/metrics", gin.WrapH(promhttp.Handler()))

	
	r.GET("/ws/agents/:agent_id", func(c *gin.Context) {
		agentID := c.Param("agent_id")
		conn, err := upgrader.Upgrade(c.Writer, c.Request, nil)
		if err != nil {
			log.Error("websocket upgrade failed", zap.Error(err))
			return
		}
		hub.Register(agentID, conn)
	})

	v1 := r.Group("/api/v1/cti")
	{
		
		v1.POST("/screen-pop", func(c *gin.Context) {
			var body struct {
				CallID   string `json:"call_id" binding:"required"`
				CallerID string `json:"caller_id" binding:"required"`
				AgentID  string `json:"agent_id" binding:"required"`
				QueueID  string `json:"queue_id"`
			}
			if err := c.ShouldBindJSON(&body); err != nil {
				c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
				return
			}
			go handler.HandleIncomingCall(c.Request.Context(), body.CallID, body.CallerID, body.AgentID, body.QueueID)
			c.JSON(http.StatusAccepted, gin.H{"status": "dispatched"})
		})

		
		v1.POST("/call-end", func(c *gin.Context) {
			var body struct {
				CallID      string `json:"call_id"`
				AgentID     string `json:"agent_id"`
				HangupCause string `json:"hangup_cause"`
			}
			c.ShouldBindJSON(&body)
			handler.HandleCallEnd(body.AgentID, body.CallID, body.HangupCause)
			c.JSON(http.StatusOK, gin.H{"status": "ok"})
		})
	}

	srv := &http.Server{Addr: ":8080", Handler: r}
	go srv.ListenAndServe()

	log.Info("CTI service started")
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	srv.Shutdown(ctx)
}
