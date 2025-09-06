import React, { useState, useEffect, useRef } from 'react';
import { useQuery, useQueryClient } from 'react-query';
import axios from 'axios';

interface EmailRow {
  id: number;
  subject: string;
  sender: string;
  priority?: string;
  sentiment?: string;
  status?: string;
}

interface EmailListProps {
  onSelect: (id: number) => void;
  selectedId: number | null;
  filters: { priority?: string; sentiment?: string; status?: string; domain?: string };
  search: string;
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  refreshKey?: number; // external trigger to force refetch
}

export const EmailList: React.FC<EmailListProps> = ({ onSelect, selectedId, filters, search, page, pageSize, onPageChange, refreshKey }) => {
  const qc = useQueryClient();
  const queryParams: Record<string,string> = { limit: String(pageSize), offset: String(page*pageSize) };
  if (filters.priority) queryParams.priority = filters.priority;
  if (filters.sentiment) queryParams.sentiment = filters.sentiment;
  if (filters.status) queryParams.status = filters.status;
  if (filters.domain) queryParams.domain = filters.domain;
  if (search) queryParams.q = search;
  const queryString = new URLSearchParams(queryParams).toString();
  const { data, refetch, isLoading, error } = useQuery<any>(['emails', filters, search, page, pageSize, refreshKey], async () => {
    const r = await axios.get(`/api/emails?${queryString}`);
    return r.data; // expects { total, items }
  }, { refetchInterval: 8000 });

  // SSE real-time updates (auto refetch on email_updated)
  const sseRef = useRef<EventSource | null>(null);
  useEffect(() => {
    if (sseRef.current) return; // single instance
    const es = new EventSource('/api/events');
    sseRef.current = es;
    es.addEventListener('email_updated', () => {
      refetch();
      qc.invalidateQueries(['analytics']);
    });
    es.onerror = () => {
      es.close();
      sseRef.current = null;
      // Attempt silent reconnect after delay
      setTimeout(() => { if(!sseRef.current) { sseRef.current = new EventSource('/api/events'); } }, 3000);
    };
    return () => { es.close(); sseRef.current = null; };
  }, [refetch, qc]);

  const items: EmailRow[] = data?.items || [];
  const total: number = data?.total || 0;
  const totalPages = Math.ceil(total / pageSize) || 1;
  const empty = !isLoading && items.length === 0;

  // If filters shrink total below current page start, trigger a refetch hint via parent (handled externally) or just show page 0 suggestion
  useEffect(() => {
    if (page > 0 && page * pageSize >= total && total > 0) {
      // naive: advise user; in full app we would call onPageChange(0)
      // but we cannot directly (prop) without risk of loop; safe invocation
      onPageChange(0);
    }
  }, [total, page, pageSize, onPageChange]);

  let content: React.ReactNode;
  if (error) {
    content = <div style={{padding:'8px', fontSize:'0.7rem', color:'red'}}>Error loading emails. Check backend is running. {String((error as any).message || '')}</div>;
  } else if (isLoading) {
    content = (
      <>
        {Array.from({length:6}).map((_,i)=>(
          <div key={i} className="email-row skeleton">
            <span style={{width:'60%'}}>&nbsp;</span>
            <span style={{width:'30%'}}>&nbsp;</span>
            <span className="badge">&nbsp;</span>
            <span className="badge">&nbsp;</span>
          </div>
        ))}
      </>
    );
  } else if (empty) {
    content = (
      <div style={{padding:'6px', fontSize:'0.7rem', color:'#555'}}>
        No emails for current filters. <button style={{fontSize:'0.6rem'}} onClick={()=> { qc.invalidateQueries(['emails']); refetch(); }}>Refresh</button>
      </div>
    );
  } else {
    content = (
      <>
        {items.map(e => (
          <div key={e.id} className={`email-row ${selectedId===e.id?'active':''}`} onClick={() => onSelect(e.id)}>
            <span className="col-subject" title={e.subject}>{e.subject}</span>
            <span className="col-sender" title={e.sender}>{e.sender}</span>
            <span className="col-priority"><span className={`badge ${e.priority==='Urgent'?'urgent':''}`}>{e.priority?.[0]}</span></span>
            <span className="col-sentiment"><span className={`badge sentiment-${(e.sentiment||'').toLowerCase()}`}>{e.sentiment?.[0]}</span></span>
            <span className="col-status">{e.status?.[0] || ''}</span>
          </div>
        ))}
        <div className="emails-footer">
          <span>{items.length ? `${offsetLabel(page,pageSize,total)} of ${total}` : '0'} | Page size: {pageSize}</span>
          <span style={{display:'flex', gap:'4px', alignItems:'center'}}>
            <button disabled={page===0} onClick={()=>onPageChange(page-1)} title="Previous page">{'<'}</button>
            <span style={{fontVariantNumeric:'tabular-nums'}}>{page+1}/{totalPages}</span>
            <button disabled={page+1>=totalPages} onClick={()=>onPageChange(page+1)} title="Next page">{'>'}</button>
          </span>
        </div>
      </>
    );
  }

  return (
    <div className="emails">
      <div className="emails-header">
        <span>Subject</span>
        <span>Sender</span>
        <span className="col-priority">Priority</span>
        <span className="col-sentiment">Sentiment</span>
        <span></span>
      </div>
      {content}
    </div>
  );
};

function offsetLabel(page:number, pageSize:number, total:number){
  const start = page*pageSize + 1;
  const end = Math.min(total, (page+1)*pageSize);
  if (total===0) return '0';
  return `${start}-${end}`;
}
