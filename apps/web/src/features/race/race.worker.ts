import type { Message, RaceFrame } from './types';

let socket: WebSocket | null = null;
let latest: RaceFrame | null = null;
let reconnect: ReturnType<typeof setTimeout>;
let stopped = false;
let previous: { at: number; frame: RaceFrame } | null = null;
let rate = 0;

function connect() {
  const url = new URL('/race/socket', self.location.href);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  socket = new WebSocket(url);
  socket.onopen = () => self.postMessage({ type: 'connection', connected: true, url: url.href });
  socket.onmessage = (event: MessageEvent<string>) => {
    try {
      const message = JSON.parse(event.data) as Message;
      if (message.type === 'frame') {
        const now = performance.now();
        if (previous?.frame.generation === message.generation
          && previous.frame.status === 'running' && message.time_s >= previous.frame.time_s) {
          const measured = (message.time_s - previous.frame.time_s) * 1000 / Math.max(1, now - previous.at);
          rate = rate ? rate * 0.8 + measured * 0.2 : measured;
        } else {
          rate = 0;
        }
        latest = { ...message, playback_rate: message.status === 'running' ? rate : 0 };
        previous = { at: now, frame: message };
      } else if (message.type === 'catalogue' || message.type === 'error') {
        self.postMessage(message);
      }
    } catch {
      self.postMessage({ type: 'error', message: 'Invalid simulator message. Reconnect to the runtime.' });
    }
  };
  socket.onclose = () => {
    self.postMessage({ type: 'connection', connected: false, url: url.href });
    if (!stopped) {
      reconnect = setTimeout(connect, 1500);
    }
  };
}

self.onmessage = (event: MessageEvent<{
  type: 'poll' | 'command' | 'stop'; payload?: Record<string, unknown>;
}>) => {
  if (event.data.type === 'poll') {
    self.postMessage({ type: 'snapshot', frame: latest });
    latest = null;
  } else if (event.data.type === 'stop') {
    stopped = true;
    clearTimeout(reconnect);
    socket?.close();
  } else if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(event.data.payload));
  } else {
    self.postMessage({ type: 'error', message: 'Simulator disconnected. Start make race-server.' });
  }
};

connect();
