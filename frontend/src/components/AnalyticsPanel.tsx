import React from 'react';
import { useQuery } from 'react-query';
import axios from 'axios';
import { Bar, Doughnut } from 'react-chartjs-2';
import { Chart, CategoryScale, LinearScale, BarElement, ArcElement, Tooltip, Legend } from 'chart.js';
Chart.register(CategoryScale, LinearScale, BarElement, ArcElement, Tooltip, Legend);

interface Summary {
  total: number;
  last_24h: number;
  sentiment: Record<string, number>;
  priority: Record<string, number>;
  resolved: number;
  pending: number;
}

export const AnalyticsPanel: React.FC = () => {
  const { data, isLoading, error } = useQuery<Summary>(['analytics'], async () => {
    const r = await axios.get('/api/analytics/summary');
    return r.data;
  }, { refetchInterval: 10000 });

  if (error) return <div style={{color:'red', fontSize:'0.7rem'}}>Failed to load analytics: {String((error as any).message||'')}</div>;
  if (isLoading || !data) return <div className="analytics"><div className="stat-cards loading"><div className="stat-card skeleton"/><div className="stat-card skeleton"/><div className="stat-card skeleton"/><div className="stat-card skeleton"/></div></div>;

  const sentimentLabels = Object.keys(data.sentiment);
  const sentimentValues = Object.values(data.sentiment);
  const priorityLabels = Object.keys(data.priority);
  const priorityValues = Object.values(data.priority);

  return (
    <div className="analytics">
      <div className="analytics-inner">
        <div className="stat-cards-vertical">
          <div className="stat-card"><div className="stat-value">{data.total}</div><div className="stat-label">Total</div></div>
          <div className="stat-card"><div className="stat-value">{data.last_24h}</div><div className="stat-label">24h</div></div>
          <div className="stat-card"><div className="stat-value">{data.pending}</div><div className="stat-label">Pending</div></div>
          <div className="stat-card"><div className="stat-value">{data.resolved}</div><div className="stat-label">Resolved</div></div>
        </div>
        <div className="analytics-chart side" style={{display:'flex', flexDirection:'row', gap:'0.75rem', width:'100%', height:'240px'}}>
          <div style={{position:'relative', flex:1, minWidth:0}}>
            <div style={{fontSize:'0.6rem', fontWeight:600, marginBottom:4}}>Sentiment</div>
            <div style={{position:'absolute', inset: '18px 4px 4px 4px'}}>
              <Bar
                data={{
                  labels: sentimentLabels,
                  datasets: [{
                    label: 'Sentiment',
                    data: sentimentValues,
                    backgroundColor: ['#16a34a','#6b7280','#dc2626']
                  }]
                }}
                options={{responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}}, animation:false, scales:{x:{ticks:{font:{size:10}}}, y:{ticks:{font:{size:10}}, beginAtZero:true}}}}
              />
              {sentimentValues.every(v=>v===0) && <div style={{position:'absolute', inset:0, display:'flex', alignItems:'center', justifyContent:'center', fontSize:'0.55rem', color:'#64748b', pointerEvents:'none'}}>No sentiment data</div>}
            </div>
          </div>
          <div style={{position:'relative', flex:1, minWidth:0}}>
            <div style={{fontSize:'0.6rem', fontWeight:600, marginBottom:4}}>Priority</div>
            <div style={{position:'absolute', inset: '4px 4px 4px 4px', display:'flex', alignItems:'center', justifyContent:'center'}}>
              <Doughnut
                data={{
                  labels: priorityLabels,
                  datasets: [{
                    label: 'Priority',
                    data: priorityValues,
                    backgroundColor: priorityLabels.map(l => l === 'Urgent' ? '#dc2626' : '#2563eb'),
                    borderWidth: 0,
                    hoverOffset: 4
                  }]
                }}
                options={{
                  responsive:true,
                  maintainAspectRatio:false,
                  cutout:'55%',
                  plugins:{
                    legend:{display:true, position:'bottom', labels:{boxWidth:10, font:{size:9}}},
                    tooltip:{callbacks:{label: (ctx)=> `${ctx.label}: ${ctx.raw}`}}
                  },
                  animation:false
                }}
              />
              {priorityValues.every(v=>v===0) && <div style={{position:'absolute', inset:0, display:'flex', alignItems:'center', justifyContent:'center', fontSize:'0.55rem', color:'#64748b', pointerEvents:'none'}}>No priority data</div>}
              {!priorityValues.every(v=>v===0) && (
                <div style={{position:'absolute', fontSize:'0.55rem', textAlign:'center', lineHeight:1.2, color:'#334155'}}>
                  {(() => {
                    const total = priorityValues.reduce((a,b)=>a+b,0);
                    if (!total) return '';
                    const urgentIdx = priorityLabels.findIndex(l=>l==='Urgent');
                    const urgent = urgentIdx>=0 ? priorityValues[urgentIdx] : 0;
                    const pct = total ? Math.round((urgent/total)*100) : 0;
                    return `Urgent\n${pct}%`;
                  })()}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
