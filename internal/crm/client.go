package crm

import (
"context"
"encoding/json"
"fmt"
"net/http"
"time"

"go.uber.org/zap"
)

type CustomerInfo struct {
ID            string            `json:"id"`
Name          string            `json:"name"`
Phone         string            `json:"phone"`
Email         string            `json:"email,omitempty"`
Segment       string            `json:"segment"`        
AccountStatus string            `json:"account_status"` 
OpenTickets   int               `json:"open_tickets"`
LastCallDate  *time.Time        `json:"last_call_date,omitempty"`
LifetimeValue float64           `json:"lifetime_value"`
CustomFields  map[string]string `json:"custom_fields,omitempty"`
}

type Client struct {
baseURL    string
apiKey     string
httpClient *http.Client
log        *zap.Logger
}

func NewClient(baseURL, apiKey string, log *zap.Logger) *Client {
return &Client{
baseURL: baseURL,
apiKey:  apiKey,
httpClient: &http.Client{
Timeout: 3 * time.Second,
},
log: log,
}
}

func (c *Client) LookupByPhone(ctx context.Context, phone string) (*CustomerInfo, error) {
url := fmt.Sprintf("%s/api/customers?phone=%s", c.baseURL, phone)

req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
if err != nil {
return nil, fmt.Errorf("build request: %w", err)
}
req.Header.Set("Authorization", "Bearer "+c.apiKey)
req.Header.Set("Accept", "application/json")

resp, err := c.httpClient.Do(req)
if err != nil {

c.log.Warn("crm.lookup.failed", zap.String("phone", phone), zap.Error(err))
return &CustomerInfo{Phone: phone, Name: "Unknown", Segment: "standard"}, nil
}
defer resp.Body.Close()

if resp.StatusCode == http.StatusNotFound {
return &CustomerInfo{Phone: phone, Name: "New Customer", Segment: "standard"}, nil
}

if resp.StatusCode != http.StatusOK {
return nil, fmt.Errorf("crm returned %d", resp.StatusCode)
}

var result struct {
Data CustomerInfo `json:"data"`
}
if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
return nil, fmt.Errorf("decode: %w", err)
}
return &result.Data, nil
}
