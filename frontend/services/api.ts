const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export function getToken(): string | null {
  if (typeof window !== 'undefined') {
    return localStorage.getItem('latext_token');
  }
  return null;
}

export function setToken(token: string) {
  if (typeof window !== 'undefined') {
    localStorage.setItem('latext_token', token);
  }
}

export function removeToken() {
  if (typeof window !== 'undefined') {
    localStorage.removeItem('latext_token');
  }
}

function parseErrorMessage(errorJson: any, status: number, statusText: string): string {
  if (!errorJson) return statusText || 'An unexpected error occurred.';

  // If detail is a string
  if (typeof errorJson.detail === 'string') {
    const d = errorJson.detail;
    // Map DST transition errors
    if (d.includes('NonExistentTimeError') || d.includes('does not exist') || d.includes('DST') || d.includes('daylight')) {
      return "This time does not exist in the selected timezone due to a Daylight Saving Time (DST) clock transition. Please choose another time.";
    }
    if (d.includes('AmbiguousTimeError') || d.includes('ambiguous')) {
      return "This time is ambiguous in the selected timezone due to a Daylight Saving Time (DST) clock rollback. Please specify a distinct time.";
    }
    // Cancellation race conditions
    if (d.includes('Cannot cancel') || d.includes('already being processed') || d.includes('SENT') || d.includes('PROCESSING')) {
      return "This message has already started sending and can no longer be cancelled.";
    }
    if (d.includes('Cannot update') || d.includes('only SCHEDULED messages')) {
      return "This message is already in transit and can no longer be edited.";
    }
    return d;
  }

  // If detail is a validation error array (FastAPI 422)
  if (Array.isArray(errorJson.detail)) {
    return errorJson.detail.map((err: any) => err.msg || err.message || JSON.stringify(err)).join(', ');
  }

  if (errorJson.message && typeof errorJson.message === 'string') {
    return errorJson.message;
  }

  if (status === 401) {
    return 'Your session has expired. Please sign in again.';
  }

  if (status === 403) {
    return 'You do not have permission to perform this action.';
  }

  if (status === 404) {
    return 'The requested resource was not found.';
  }

  if (status >= 500) {
    return 'The server encountered an error. Please try again shortly.';
  }

  return JSON.stringify(errorJson);
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers || {});
  
  // JSON content type by default unless body is FormData
  if (!(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  // Attach JWT token if present
  const token = getToken();
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      ...options,
      headers,
    });
  } catch (err: any) {
    throw new Error(err.message || 'Network error. Please verify your connection to the server.');
  }

  if (!response.ok) {
    let errorDetail = response.statusText || 'An error occurred';
    try {
      const errorJson = await response.json();
      errorDetail = parseErrorMessage(errorJson, response.status, response.statusText);
    } catch {
      errorDetail = response.statusText || errorDetail;
    }
    throw new Error(errorDetail);
  }

  // Handle 201 Created or 204 No Content returning no data
  if (response.status === 204) {
    return {} as T;
  }

  return response.json();
}

export const api = {
  // Authentication
  register: (body: any) => request('/auth/register', { method: 'POST', body: JSON.stringify(body) }),
  login: (body: any) => request<{ access_token: string }>('/auth/login', { method: 'POST', body: JSON.stringify(body) }),
  
  // Users
  getMe: () => request<any>('/users/me'),
  searchUsers: (q: string) => request<any[]>(`/users/search?q=${encodeURIComponent(q)}`),

  // Conversations
  getConversations: () => request<any[]>('/conversations'),
  createConversation: (recipientId: string) => request<any>('/conversations', {
    method: 'POST',
    body: JSON.stringify({ recipient_id: recipientId }),
  }),

  // Messages
  getMessages: (conversationId: string) => request<any[]>(`/conversations/${conversationId}/messages`),
  sendMessage: (conversationId: string, content: string) => request<any>(`/conversations/${conversationId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  }),

  // Scheduled Messages
  createScheduledMessage: (body: { conversation_id: string; content: string; message_type?: string; scheduled_at: string; timezone: string }) => 
    request<any>('/scheduled-messages', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  getScheduledMessages: (status?: string) => 
    request<any[]>(`/scheduled-messages${status ? `?status=${status}` : ''}`),
  getScheduledMessage: (id: string) => 
    request<any>(`/scheduled-messages/${id}`),
  updateScheduledMessage: (id: string, body: { content?: string; scheduled_at?: string; timezone?: string }) => 
    request<any>(`/scheduled-messages/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  cancelScheduledMessage: (id: string) => 
    request<any>(`/scheduled-messages/${id}`, {
      method: 'DELETE',
    }),
};
