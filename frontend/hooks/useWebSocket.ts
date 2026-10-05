import { useEffect, useRef, useState, useCallback } from 'react';
import { getToken } from '@/services/api';

export function useWebSocket(
  conversationId: string | null,
  onMessageReceived: (message: any) => void,
  onStatusUpdate: (update: { message_id: string; status: string }) => void
) {
  const [status, setStatus] = useState<'CONNECTING' | 'OPEN' | 'CLOSED'>('CLOSED');
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<any>(null);
  const reconnectDelayRef = useRef(1000);

  const connect = useCallback(() => {
    if (!conversationId) return;

    const token = getToken();
    if (!token) return;

    if (wsRef.current) {
      wsRef.current.close();
    }

    setStatus('CONNECTING');

    const wsBaseUrl = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000';
    const wsUrl = `${wsBaseUrl}/ws/${conversationId}?token=${encodeURIComponent(token)}`;
    
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      setStatus('OPEN');
      reconnectDelayRef.current = 1000; // Reset backoff delay on success
    };

    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.event === 'message') {
          onMessageReceived(payload.data);
        } else if (payload.event === 'status_update') {
          onStatusUpdate(payload.data);
        }
      } catch (err) {
        console.error('Failed to parse WebSocket message:', err);
      }
    };

    ws.onclose = () => {
      setStatus('CLOSED');
      // Trigger reconnect using bounded exponential backoff (max 16 seconds)
      reconnectTimeoutRef.current = setTimeout(() => {
        reconnectDelayRef.current = Math.min(reconnectDelayRef.current * 2, 16000);
        connect();
      }, reconnectDelayRef.current);
    };

    ws.onerror = (err) => {
      console.error('WebSocket error:', err);
      ws.close();
    };
  }, [conversationId, onMessageReceived, onStatusUpdate]);

  useEffect(() => {
    connect();

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
    };
  }, [conversationId, connect]);

  const sendEvent = useCallback((event: string, data: any) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ event, data }));
      return true;
    }
    return false;
  }, []);

  return { status, sendEvent };
}
