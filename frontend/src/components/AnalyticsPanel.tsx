import React from 'react';
import { useQuery } from 'react-query';
import axios from 'axios';
import { Bar } from 'react-chartjs-2';
import { Chart, CategoryScale, LinearScale, BarElement, Tooltip, Legend } from 'chart.js';
Chart.register(CategoryScale, LinearScale, BarElement, Tooltip, Legend);
// ECharts donut for priority distribution
import * as echarts from 'echarts';
import ReactECharts from 'echarts-for-react';

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

  // Build ECharts donut option
  const totalPriority = priorityValues.reduce((a,b)=>a+b,0);
  const prioritySeriesData = priorityLabels.map((label, idx) => ({
    name: label,
    value: priorityValues[idx]
  }));

  // Map explicit priority colors (Urgent=red, Not urgent=sky blue). Case-insensitive.
  const priorityColorFor = (name: string) => {
    const n = (name||'').toLowerCase();
    if (n.includes('urgent')) {
      if (n.startsWith('not')) {
        // Not urgent -> sky blue gradient
        return new echarts.graphic.LinearGradient(0,0,1,1,[{offset:0,color:'#38bdf8'},{offset:1,color:'#0ea5e9'}]);
      }
      // Urgent -> red gradient
      return new echarts.graphic.LinearGradient(0,0,1,1,[{offset:0,color:'#f87171'},{offset:1,color:'#dc2626'}]);
    }
    // Fallback other buckets
    return new echarts.graphic.LinearGradient(0,0,1,1,[{offset:0,color:'#94a3b8'},{offset:1,color:'#64748b'}]);
  };

  const priorityOption = {
    tooltip: {
      trigger: 'item',
      formatter: (p:any) => `${p.name}: ${p.value} (${p.percent}%)`
    },
    legend: {
      orient: 'vertical',
      left: 'left',
      top: 'middle',
      icon: 'circle',
      textStyle: { fontSize: 10 }
    },
    series: [
      {
        name: 'Priority',
        type: 'pie',
        radius: ['55%','80%'],
        center: ['60%','50%'],
        avoidLabelOverlap: true,
        minAngle: 4,
        itemStyle: {
          borderRadius: 4,
          borderColor: '#fff',
          borderWidth: 2
        },
        label: {
            show: true,
            formatter: (p:any) => p.value ? `${p.name}\n${p.value}` : '' ,
            fontSize: 10,
            lineHeight: 12
        },
        labelLine: { length: 10, length2: 6 },
  data: prioritySeriesData.map(d=> ({...d, itemStyle:{ color: priorityColorFor(d.name)}}))
      }
    ]
  };

  return (
    <div className="analytics">
      <div className="analytics-inner">
        <div className="stat-cards-vertical">
          <div className="stat-card"><div className="stat-value">{data.total}</div><div className="stat-label">Total</div></div>
          <div className="stat-card"><div className="stat-value">{data.last_24h}</div><div className="stat-label">24h</div></div>
          <div className="stat-card"><div className="stat-value">{data.pending}</div><div className="stat-label">Pending</div></div>
          <div className="stat-card"><div className="stat-value">{data.resolved}</div><div className="stat-label">Resolved</div></div>
        </div>
        <div className="analytics-chart side" style={{display:'flex', flexDirection:'row', gap:'0.75rem', width:'100%', minHeight:'240px'}}>
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
          <div style={{position:'relative', flex:1, minWidth:0, display:'flex', flexDirection:'column'}}>
            <div style={{fontSize:'0.6rem', fontWeight:600, marginBottom:4}}>Priority (Donut)</div>
            <div style={{flex:1, minHeight:0}}>
              {totalPriority === 0 ? (
                <div style={{position:'absolute', inset:0, display:'flex', alignItems:'center', justifyContent:'center', fontSize:'0.55rem', color:'#64748b'}}>No priority data</div>
              ) : (
                <ReactECharts style={{height:'100%', minHeight:'180px'}} option={priorityOption} notMerge={true} lazyUpdate={true} />
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
