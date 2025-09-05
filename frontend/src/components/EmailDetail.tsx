import React, { useState } from 'react';
import { useQuery, useQueryClient } from 'react-query';
import axios from 'axios';

interface EmailFull {
  id: number;
  subject: string;
  body: string;
  sender: string;
  received_at?: string;
  priority?: string;
  sentiment?: string;
  auto_response?: string | null;
  status?: string;
  extracted?: {
    phone_numbers?: string[];
    alt_emails?: string[];
    sentiment?: string;
    priority?: string;
  keywords?: string[];
  requested_actions?: string[];
  sentiment_terms?: string[];
  }
}

async function fetchEmail(id: number): Promise<EmailFull | null> {
  const r = await axios.get(`/api/emails/${id}`);
  return r.data;
}

export const EmailDetail: React.FC<{ id: number | null }> = ({ id }) => {
  const qc = useQueryClient();
  const { data, isLoading, error, refetch } = useQuery(['email', id], () => id ? fetchEmail(id) : Promise.resolve(null), {
    enabled: !!id,
    staleTime: 5000,
    retry: 1,
    onError: (e) => { /* optional logging */ console.warn('Email detail load error', e); }
  });
  const [isRegenerating, setIsRegenerating] = useState(false);

  if (!id) return <div className="detail">Select an email from Sidebar.</div>;
  if (error) return <div className="detail" style={{color:'red', fontSize:'0.75rem'}}>
    Failed to load email (id={id}). <button onClick={()=>refetch()}>Retry</button>
    <br />{String((error as any).message || '')}
  </div>;
  if (isLoading || !data) return <div className="detail">Loading email #{id}...</div>;

  const updateResponse = async () => {
    const newText = prompt('Edit response', data.auto_response || '') || undefined;
    if (!newText) return;
    await axios.put(`/api/emails/${id}/response`, null, { params: { new_text: newText } });
    qc.invalidateQueries(['emails']);
    qc.invalidateQueries(['email', id]);
  };

  const regenerate = async () => {
    if (!id || isRegenerating) return;
    setIsRegenerating(true);
    try {
      const r = await axios.post(`/api/emails/${id}/regenerate`);
      // Optimistically update the cache with fresh response
      qc.setQueryData(['email', id], r.data);
      // Refresh list view
      qc.invalidateQueries(['emails']);
    } catch (e:any) {
      alert('Regenerate failed: ' + (e?.response?.data?.detail || e.message || 'unknown error'));
    } finally {
      // Ensure a background refetch in case of any race conditions
      qc.invalidateQueries(['email', id]);
      qc.refetchQueries(['email', id]);
      setIsRegenerating(false);
    }
  };

  return (
    <div className="detail" style={{flex:1, display:'flex', flexDirection:'column', overflow:'auto'}}>
      <h3>{data.subject}</h3>
      <div className="meta" style={{alignItems:'center'}}>
        <span>{data.sender}</span>
        <span className={`badge ${data.priority==='Urgent'?'urgent':''}`} style={{marginLeft:4}}>{data.priority}</span>
        <span className={`badge sentiment-${(data.sentiment||'').toLowerCase()}`} style={{marginLeft:2}}>{data.sentiment}</span>
      </div>
      <pre className="body">{data.body}</pre>
      <h4 style={{marginTop:'0.75rem'}}>Extracted Information</h4>
      <div style={{fontSize:'0.65rem', lineHeight:1.4, display:'grid', gap:4}}>
  <div><strong>Contact details:</strong> Not provided</div>
        <div><strong>Keywords:</strong> {data.extracted?.keywords?.length ? data.extracted.keywords.join(', ') : 'Not provided'}</div>
  <div><strong>Date:</strong> {data.received_at ? new Date(data.received_at).toLocaleDateString() : 'Not provided'}</div>
        <div><strong>Actions:</strong> {data.extracted?.requested_actions?.length ? data.extracted.requested_actions.join(', ') : 'Not provided'}</div>
      </div>
      <h4>AI Draft Response</h4>
      <pre className="response-box">{data.auto_response || '(pending...)'}</pre>
      <div style={{display:'flex', flexWrap:'wrap', gap:'0.5rem', marginTop:'0.5rem', marginBottom:'1rem'}}>
        <button onClick={updateResponse}>Edit / Save</button>
        <button onClick={regenerate} disabled={isRegenerating}>{isRegenerating ? 'Regenerating...' : 'Regenerate'}</button>
        <button
          onClick={async ()=> {
            if (!id) return;
            try {
              if (data.status === 'responded' || data.status === 'resolved') return;
              // prefer approve endpoint (marks responded if auto_response exists)
              await axios.post(`/api/emails/${id}/approve`);
              qc.invalidateQueries(['emails']);
              qc.invalidateQueries(['email', id]);
            } catch (e:any) {
              alert('Failed to mark responded: ' + (e?.response?.data?.detail || e.message || 'unknown error'));
            }
          }}
          disabled={data.status === 'responded' || data.status === 'resolved' || !data.auto_response}
          title={!data.auto_response ? 'No draft response yet' : (data.status==='responded'?'Already responded': data.status==='resolved' ? 'Already resolved' : 'Mark as responded')}>
          Responded to Customer
        </button>
        <button
          onClick={async ()=> {
            if (!id) return;
            try {
              if (data.status === 'resolved') return;
              await axios.post(`/api/emails/${id}/resolve`);
              qc.invalidateQueries(['emails']);
              qc.invalidateQueries(['email', id]);
            } catch (e:any) {
              alert('Failed to resolve: ' + (e?.response?.data?.detail || e.message || 'unknown error'));
            }
          }}
          disabled={data.status === 'resolved'}
          title={data.status==='resolved' ? 'Already resolved' : 'Mark ticket resolved'}>
          Resolved
        </button>
      </div>
    </div>
  );
};
