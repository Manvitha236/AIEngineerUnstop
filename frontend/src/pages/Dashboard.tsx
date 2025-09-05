import React, { useEffect } from 'react';
import axios from 'axios';

// minimal typing for Vite env (avoid TS error without full env.d.ts)
declare global {
  interface ImportMeta { env: Record<string, string>; }
}
import { EmailList } from '../components/EmailList';
import { AnalyticsPanel } from '../components/AnalyticsPanel';
import { EmailDetail } from '../components/EmailDetail';
import { useState } from 'react';
import './dashboard.css';

export const Dashboard: React.FC = () => {
  // Configure axios once (could load from env via import.meta.env)
  useEffect(() => {
    if (!axios.defaults.headers.common['X-API-Key']) {
  const key = (window as any).__SUPPORT_API_KEY__ || import.meta.env.VITE_SUPPORT_API_KEY || 'dev123';
      if (key) axios.defaults.headers.common['X-API-Key'] = key;
    }
  }, []);
  const [ragInfo, setRagInfo] = useState<{mode:string;status:string}|null>(null);
  useEffect(()=>{
    let timer: any;
    const poll = async () => {
      try { const r = await fetch('/health'); const j = await r.json(); setRagInfo(j.rag); } catch {}
      timer = setTimeout(poll, 5000);
    };
    poll();
    return ()=> timer && clearTimeout(timer);
  }, []);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [priorityFilter, setPriorityFilter] = useState('');
  const [sentimentFilter, setSentimentFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [page, setPage] = useState(0);
  const [categoryFilter, setCategoryFilter] = useState<string>('');
  const [domainFilter, setDomainFilter] = useState('');
  const [fuzzy, setFuzzy] = useState(false);
  const [pageSize, setPageSize] = useState(10);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 350);
    return () => clearTimeout(t);
  }, [search]);
  const [refreshKey, setRefreshKey] = useState(0);
  const [recomputeRunning, setRecomputeRunning] = useState(false);
  const [mode, setMode] = useState<'demo'|'gmail'>('demo');
  // fetch current mode on mount
  useEffect(()=>{
    (async ()=> {
      try {
        const keyVal = String(axios.defaults.headers.common['X-API-Key'] || 'dev123');
        const r = await fetch('/api/emails/fetch/mode', { headers: { 'X-API-Key': keyVal } });
        if (r.ok){
          const j = await r.json();
          if (j.provider === 'gmail') setMode('gmail');
        }
      } catch {}
    })();
  },[]);
  const switchMode = async (next: 'demo'|'gmail') => {
    if (next === mode) return;
    try {
      const apiKey = String(axios.defaults.headers.common['X-API-Key'] || 'dev123');
      const params = new URLSearchParams({ provider: next, reload_demo: (next==='demo').toString() });
      await fetch(`/api/emails/fetch/mode?${params}`, { method:'POST', headers:{ 'X-API-Key': apiKey }});
      setMode(next);
      setRefreshKey(k=>k+1);
    } catch (e) { console.warn('Switch mode failed', e); }
  };
  const seedSamples = async () => {
    const now = new Date().toISOString();
    const samples = [
      { sender: 'seed1@example.com', subject: 'Login issue cannot access', body: 'Locked out please urgent help', received_at: now },
      { sender: 'seed2@example.com', subject: 'Billing overcharged', body: 'I was overcharged on last invoice', received_at: now },
      { sender: 'seed3@example.com', subject: 'Great product feedback', body: 'Loving the new release amazing work team', received_at: now }
    ];
    for (const s of samples) {
      try { await fetch('/api/emails/ingest', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(s)}); } catch {}
    }
    setRefreshKey(k=>k+1);
  };
  const recomputeExtraction = async () => {
    try {
      if (recomputeRunning) return;
      setRecomputeRunning(true);
      const apiKey = String(axios.defaults.headers.common['X-API-Key'] || 'dev123');
      await fetch('/api/emails/maintenance/recompute', { method:'POST', headers:{ 'X-API-Key': apiKey } });
      setRefreshKey(k=>k+1);
    } catch (e) { console.warn('Recompute failed', e); }
    finally { setTimeout(()=> setRecomputeRunning(false), 400); }
  };
  const [showDashboard, setShowDashboard] = useState(false);
  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="filters">
          <h2 style={{marginTop:0, display:'flex', justifyContent:'space-between', alignItems:'center'}}>Support Inbox <span style={{fontSize:'0.55rem', fontWeight:500, opacity:0.7}}>{ragInfo?`RAG:${ragInfo.status}`:''}</span></h2>
          <div style={{display:'flex', gap:4, marginBottom:4}}>
            <button onClick={()=>switchMode('demo')} className={mode==='demo'? 'active-mode':''} style={{padding:'4px 8px', fontSize:'0.55rem', background: mode==='demo'? '#475569':'#e2e8f0', color: mode==='demo'? '#fff':'#334155'}} >Demo</button>
            <button onClick={()=>switchMode('gmail')} className={mode==='gmail'? 'active-mode':''} style={{padding:'4px 8px', fontSize:'0.55rem', background: mode==='gmail'? '#475569':'#e2e8f0', color: mode==='gmail'? '#fff':'#334155'}} >Live Gmail</button>
          </div>
          <input placeholder="Search subject or body" value={search} onChange={e=> { setSearch(e.target.value); setPage(0);} } />
          <div style={{display:'flex', gap:4, flexWrap:'wrap', margin:'4px 0'}}>
            {['support','query','request','help'].map(cat => (
              <button
                key={cat}
                onClick={()=> { setCategoryFilter(c=> c===cat ? '' : cat); setPage(0); setRefreshKey(k=>k+1);} }
                style={{
                  fontSize:'0.55rem',
                  padding:'2px 6px',
                  border:'1px solid #475569',
                  background: categoryFilter===cat ? '#475569' : 'transparent',
                  color: categoryFilter===cat ? '#fff':'#475569',
                  borderRadius:4,
                  cursor:'pointer'
                }}>{cat}</button>
            ))}
          </div>
          <div className="inline-group">
            <input placeholder="Domain (example.com)" value={domainFilter} onChange={e=> { setDomainFilter(e.target.value); setPage(0);} } style={{flex:1}} />
            <label style={{fontSize:'0.6rem', display:'flex', alignItems:'center', gap:4}}>
              <input type="checkbox" checked={fuzzy} onChange={e=> { setFuzzy(e.target.checked); setPage(0);} } /> Fuzzy
            </label>
          </div>
          <div className="inline-group">
            <select value={priorityFilter} onChange={e => { setPriorityFilter(e.target.value); setPage(0);} } style={{flex:1}}>
              <option value="">Priority</option>
              <option value="urgent">Urgent</option>
              <option value="high">High</option>
              <option value="normal">Normal</option>
              <option value="low">Low</option>
            </select>
            <select value={sentimentFilter} onChange={e => { setSentimentFilter(e.target.value); setPage(0);} } style={{flex:1}}>
              <option value="">Sentiment</option>
              <option value="positive">Positive</option>
              <option value="negative">Negative</option>
              <option value="neutral">Neutral</option>
            </select>
            <select value={statusFilter} onChange={e => { setStatusFilter(e.target.value); setPage(0);} } style={{flex:1}}>
              <option value="">Status</option>
              <option value="pending">Pending</option>
              <option value="responded">Responded</option>
              <option value="resolved">Resolved</option>
            </select>
          </div>
          <div className="inline-group" style={{justifyContent:'flex-start', alignItems:'center', flexWrap:'wrap'}}>
            <button onClick={()=> setRefreshKey(k=>k+1)}>↻ Refresh</button>
            <button onClick={recomputeExtraction} disabled={recomputeRunning} title="Re-run extraction on all emails">
              {recomputeRunning ? 'Recomputing…' : 'Recompute'}
            </button>
            {recomputeRunning && <span style={{fontSize:'0.55rem', color:'#475569'}}>Updating extractions…</span>}
            <label style={{fontSize:'0.6rem', fontWeight:500, display:'flex', alignItems:'center', gap:4}}>Size
              <select value={pageSize} onChange={e => { setPageSize(Number(e.target.value)); setPage(0); }}>
                <option value={10}>10</option>
                <option value={25}>25</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
              </select>
            </label>
          </div>
        </div>
  <EmailList refreshKey={refreshKey} onSelect={setSelectedId} selectedId={selectedId} filters={{ priority: priorityFilter || undefined, sentiment: sentimentFilter || undefined, status: statusFilter || undefined, domain: domainFilter || undefined, fuzzy: fuzzy || undefined }} search={categoryFilter ? `${debounced} ${categoryFilter}`.trim() : debounced} page={page} pageSize={pageSize} onPageChange={setPage} />
      </aside>
      <main className="main">
        <div style={{position:'relative', flex:1, display:'flex', flexDirection:'column', gap:'0.5rem', minHeight:0}}>
          <div style={{flex:1, minHeight:0, display:'flex'}}>
            <EmailDetail id={selectedId} />
          </div>
          {!showDashboard && (
            <div style={{display:'flex', justifyContent:'center', padding:'2px 0'}}>
              <button className="dash-toggle-btn" onClick={()=> setShowDashboard(true)}>Click here to see dashboard</button>
            </div>
          )}
          <div className={`dashboard-slide ${showDashboard? 'open':'closed'}`} style={{marginTop: showDashboard? '4px':'0'}}>
            <div className="dashboard-header" style={{position:'relative', justifyContent:'center'}}>
              <span style={{fontSize:'0.8rem', fontWeight:700, letterSpacing:'0.5px'}}>Dashboard</span>
              <button aria-label="Hide dashboard" className="icon-btn" onClick={()=> setShowDashboard(false)} style={{position:'absolute', right:6, top:4}}>✕</button>
            </div>
            <div className="dashboard-body">
              <AnalyticsPanel />
            </div>
          </div>
        </div>
      </main>
    </div>
  );
};
