package kafka

import (
"context"
"encoding/json"
"fmt"

"github.com/confluentinc/confluent-kafka-go/v2/kafka"
"go.uber.org/zap"
)

type Event struct {
Type    string          `json:"type"`
Payload json.RawMessage `json:"payload"`
}

type Consumer struct {
consumer *kafka.Consumer
logger   *zap.Logger
}

func NewConsumer(brokers, groupID string, topics []string, logger *zap.Logger) (*Consumer, error) {
c, err := kafka.NewConsumer(&kafka.ConfigMap{
"bootstrap.servers":    brokers,
"group.id":             groupID,
"auto.offset.reset":    "earliest",
"enable.auto.commit":   false,
"isolation.level":      "read_committed",
"session.timeout.ms":   30000,
"max.poll.interval.ms": 300000,
"heartbeat.interval.ms": 3000,
})
if err != nil {
return nil, fmt.Errorf("creating kafka consumer: %w", err)
}
if err := c.SubscribeTopics(topics, nil); err != nil {
return nil, fmt.Errorf("subscribing to topics %v: %w", topics, err)
}
return &Consumer{consumer: c, logger: logger}, nil
}

func (c *Consumer) Consume(ctx context.Context, handler func(Event) error) {
for {
select {
case <-ctx.Done():
c.logger.Info("kafka consumer stopping")
_ = c.consumer.Close()
return
default:
}

msg, err := c.consumer.ReadMessage(100)
if err != nil {
if kerr, ok := err.(kafka.Error); ok && kerr.Code() == kafka.ErrTimedOut {
continue
}
c.logger.Error("kafka read error", zap.Error(err))
continue
}

var event Event
if err := json.Unmarshal(msg.Value, &event); err != nil {
c.logger.Warn("failed to unmarshal event", zap.ByteString("raw", msg.Value), zap.Error(err))
_, _ = c.consumer.CommitMessage(msg)
continue
}

if err := handler(event); err != nil {
c.logger.Error("event handler error", zap.String("type", event.Type), zap.Error(err))
}

if _, err := c.consumer.CommitMessage(msg); err != nil {
c.logger.Warn("commit failed", zap.Error(err))
}
}
}

type Producer struct {
producer *kafka.Producer
logger   *zap.Logger
}

func NewProducer(brokers string, logger *zap.Logger) (*Producer, error) {
p, err := kafka.NewProducer(&kafka.ConfigMap{
"bootstrap.servers":             brokers,
"enable.idempotence":            true,
"compression.type":              "snappy",
"acks":                          "all",
"retries":                       10,
"retry.backoff.ms":              200,
"queue.buffering.max.messages":  100000,
"queue.buffering.max.kbytes":    1048576,
"linger.ms":                     5,
})
if err != nil {
return nil, fmt.Errorf("creating kafka producer: %w", err)
}

go func() {
for e := range p.Events() {
if m, ok := e.(*kafka.Message); ok && m.TopicPartition.Error != nil {
logger.Error("delivery failed",
zap.String("topic", *m.TopicPartition.Topic),
zap.Error(m.TopicPartition.Error),
)
}
}
}()

return &Producer{producer: p, logger: logger}, nil
}

func (p *Producer) Publish(topic, key string, v interface{}) error {
data, err := json.Marshal(v)
if err != nil {
return fmt.Errorf("marshalling event: %w", err)
}
return p.producer.Produce(&kafka.Message{
TopicPartition: kafka.TopicPartition{Topic: &topic, Partition: kafka.PartitionAny},
Key:            []byte(key),
Value:          data,
}, nil)
}

func (p *Producer) Close() {
p.producer.Flush(5000)
p.producer.Close()
}
