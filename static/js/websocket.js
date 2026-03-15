/**
 * WebSocket 客户端 - 实时接收价格和指标更新
 */
class PriceWebSocket {
  constructor(url) {
    this.url = url;
    this.ws = null;
    this.reconnectDelay = 3000;
    this.maxRetries = 10;
    this.retryCount = 0;
    this.handlers = {};
    this.connect();
  }

  connect() {
    if (this.retryCount >= this.maxRetries) {
      console.error('达到最大重连次数');
      this.updateStatus('连接失败');
      return;
    }

    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        console.log('WebSocket connected');
        this.retryCount = 0;
        this.updateStatus('在线');

        // 发送心跳
        this.startHeartbeat();
      };

      this.ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          this.handleMessage(message);
        } catch (error) {
          console.error('Failed to parse WebSocket message:', error);
        }
      };

      this.ws.onclose = () => {
        console.log('WebSocket disconnected');
        this.updateStatus('离线');
        this.stopHeartbeat();
        this.retryCount++;

        // 自动重连
        setTimeout(() => this.connect(), this.reconnectDelay);
      };

      this.ws.onerror = (error) => {
        console.error('WebSocket error:', error);
      };
    } catch (error) {
      console.error('Failed to create WebSocket:', error);
      this.retryCount++;
      setTimeout(() => this.connect(), this.reconnectDelay);
    }
  }

  startHeartbeat() {
    this.heartbeatInterval = setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send('ping');
      }
    }, 30000); // 每30秒发送一次心跳
  }

  stopHeartbeat() {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
  }

  handleMessage(message) {
    const { type, data } = message;

    switch (type) {
      case 'price_update':
        this.handlePriceUpdate(data);
        break;
      case 'indicators_update':
        this.handleIndicatorsUpdate(data);
        break;
      case 'signal_alert':
        this.handleSignalAlert(data);
        break;
      case 'pong':
        // 心跳响应
        break;
      default:
        console.warn('Unknown message type:', type);
    }

    // 调用注册的处理器
    if (this.handlers[type]) {
      this.handlers[type](data);
    }
  }

  handlePriceUpdate(data) {
    // 更新当前价格显示
    if (window.updatePrice) {
      window.updatePrice(data);
    }

    // 触发自定义事件
    window.dispatchEvent(new CustomEvent('price-update', { detail: data }));
  }

  handleIndicatorsUpdate(data) {
    // 更新指标显示
    if (window.updateIndicators) {
      window.updateIndicators(data);
    }

    // 触发自定义事件
    window.dispatchEvent(new CustomEvent('indicators-update', { detail: data }));
  }

  handleSignalAlert(data) {
    // 显示买入信号提醒
    if (window.showSignalAlert) {
      window.showSignalAlert(data);
    }

    // 触发自定义事件
    window.dispatchEvent(new CustomEvent('signal-alert', { detail: data }));

    // 浏览器通知(如果用户授权)
    if ('Notification' in window && Notification.permission === 'granted') {
      new Notification('黄金价格买入提醒', {
        body: `当前价格: ¥${data.price}/克\n${data.reason}`,
        icon: '/static/favicon.ico'
      });
    }
  }

  updateStatus(status) {
    const statusElement = document.getElementById('status-pill');
    if (statusElement) {
      statusElement.textContent = status;
      statusElement.className = 'status-pill ' + (status === '在线' ? 'online' : 'offline');
    }
  }

  on(type, handler) {
    this.handlers[type] = handler;
  }

  close() {
    this.maxRetries = 0; // 阻止自动重连
    this.stopHeartbeat();
    if (this.ws) {
      this.ws.close();
    }
  }
}

// 初始化 WebSocket 连接
let priceWS = null;

function initWebSocket() {
  // 检查 WebSocket 支持
  if (!('WebSocket' in window)) {
    console.warn('WebSocket not supported, falling back to polling');
    return null;
  }

  // 构建 WebSocket URL
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  const wsUrl = `${protocol}//${host}/ws`;

  priceWS = new PriceWebSocket(wsUrl);

  // 请求通知权限
  if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission();
  }

  return priceWS;
}

// 页面加载时初始化
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initWebSocket);
} else {
  initWebSocket();
}

// 页面卸载时关闭连接
window.addEventListener('beforeunload', () => {
  if (priceWS) {
    priceWS.close();
  }
});
