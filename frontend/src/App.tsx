import React, { useState, useRef, useEffect } from 'react';

// Types
interface Breakdown {
  tts: number;
  stt: number;
  chatbase: number;
  eval: number;
}

interface ResultItem {
  id: number;
  audio_url?: string;
  question: string;
  reference_answer?: string;
  stt_text?: string;
  ai_answer?: string;
  score?: number;
  latency?: number;
  breakdown?: Breakdown;
  status: 'pending' | 'success' | 'error';
  error?: string;
}

interface Stats {
  processed: number;
  total: number;
  avg_score: number;
  avg_latency: number;
}

function App() {
  const [file, setFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [stats, setStats] = useState<Stats>({ processed: 0, total: 0, avg_score: 0, avg_latency: 0 });
  const [results, setResults] = useState<ResultItem[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  const [sortConfig, setSortConfig] = useState<{ key: keyof ResultItem; direction: 'asc' | 'desc' } | null>(null);

  // Config State
  const [showConfig, setShowConfig] = useState(false);
  const [phraseHints, setPhraseHints] = useState<string[]>([]);
  const [newHint, setNewHint] = useState('');
  const [sttProvider, setSttProvider] = useState('google'); // 'google' or 'openai'

  // Column Mapping State
  const [availableColumns, setAvailableColumns] = useState<string[]>([]);
  const [columnMapping, setColumnMapping] = useState({ id: '', question: '', answer: '' });
  const [showMapping, setShowMapping] = useState(false);

  // API Base URL
  const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';
  const WS_BASE = API_BASE.replace(/^http/, 'ws');

  // Persistence
  useEffect(() => {
    const savedResults = localStorage.getItem('test_results');
    const savedStats = localStorage.getItem('test_stats');
    if (savedResults) setResults(JSON.parse(savedResults));
    if (savedStats) setStats(JSON.parse(savedStats));

    // Fetch initial config
    fetch(`${API_BASE}/config`)
      .then(res => res.json())
      .then(data => {
        setPhraseHints(data.phrase_hints);
        if (data.stt_provider) setSttProvider(data.stt_provider);
      })
      .catch(console.error);
  }, []);

  useEffect(() => {
    localStorage.setItem('test_results', JSON.stringify(results));
    localStorage.setItem('test_stats', JSON.stringify(stats));
  }, [results, stats]);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const selectedFile = e.target.files[0];
      setFile(selectedFile);

      // Parse headers
      const reader = new FileReader();
      reader.onload = (event) => {
        const text = event.target?.result as string;
        const firstLine = text.split('\n')[0];
        const headers = firstLine.split(',').map(h => h.trim());
        setAvailableColumns(headers);

        // Auto-detect
        const mapping = { id: '', question: '', answer: '' };
        headers.forEach(h => {
          const lower = h.toLowerCase();
          if (lower === 'id') mapping.id = h;
          if (lower.includes('question') || lower.includes('問題') || h === 'Q-ch') mapping.question = h;
          if (lower.includes('answer') || lower.includes('回答') || h === 'Ans-ch') mapping.answer = h;
        });
        setColumnMapping(mapping);
        setShowMapping(true);
      };
      reader.readAsText(selectedFile);
    }
  };

  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const handleUpload = async () => {
    if (!file) return;
    setIsUploading(true);
    setErrorMsg(null);

    const formData = new FormData();
    formData.append('file', file);
    formData.append('id_col', columnMapping.id);
    formData.append('question_col', columnMapping.question);
    formData.append('answer_col', columnMapping.answer);
    formData.append('stt_provider', sttProvider);

    try {
      const res = await fetch(`${API_BASE}/upload`, {
        method: 'POST',
        body: formData,
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.message || `Server error: ${res.status}`);
      }

      console.log('Upload success:', data);

      // Initialize results with pending items
      if (!data.items || !Array.isArray(data.items)) {
        throw new Error('Invalid response format: items missing');
      }

      const initialResults: ResultItem[] = data.items.map((item: any) => ({
        id: item.id,
        question: item.question,
        reference_answer: item.reference_answer,
        status: 'pending'
      }));

      setResults(initialResults);
      setStats({ processed: 0, total: data.item_count, avg_score: 0, avg_latency: 0 });
      setShowMapping(false);

    } catch (err: any) {
      console.error('Upload failed:', err);
      setErrorMsg(err.message || 'Upload failed');
    } finally {
      setIsUploading(false);
    }
  };

  const updateHints = async (newHints: string[]) => {
    try {
      await fetch(`${API_BASE}/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phrase_hints: newHints, stt_provider: sttProvider }),
      });
      setPhraseHints(newHints);
    } catch (err) {
      console.error('Failed to update hints:', err);
    }
  };

  const addHint = () => {
    if (newHint && !phraseHints.includes(newHint)) {
      updateHints([...phraseHints, newHint]);
      setNewHint('');
    }
  };

  const removeHint = (hint: string) => {
    updateHints(phraseHints.filter(h => h !== hint));
  };

  const handleStartTest = () => {
    if (results.length === 0) return;
    startTest(results);
  };

  const handleStopTest = () => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setIsTesting(false);
  };

  const handleExport = () => {
    const headers = ['ID', 'Original Question', 'Ref Answer', 'STT Output', 'AI Answer', 'Score', 'Latency', 'TTS Latency', 'STT Latency', 'Chatbase Latency', 'Eval Latency'];
    const csvContent = [
      '\uFEFF' + headers.join(','), // Add BOM for Excel
      ...results.map(row => [
        row.id,
        `"${(row.question || '').replace(/"/g, '""')}"`,
        `"${(row.reference_answer || '').replace(/"/g, '""')}"`,
        `"${(row.stt_text || '').replace(/"/g, '""')}"`,
        `"${(row.ai_answer || '').replace(/"/g, '""')}"`,
        row.score || '',
        row.latency || '',
        row.breakdown?.tts || '',
        row.breakdown?.stt || '',
        row.breakdown?.chatbase || '',
        row.breakdown?.eval || ''
      ].join(','))
    ].join('\n');

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    link.setAttribute('href', url);
    link.setAttribute('download', 'test_results.csv');
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const requestSort = (key: keyof ResultItem) => {
    let direction: 'asc' | 'desc' = 'asc';
    if (sortConfig && sortConfig.key === key && sortConfig.direction === 'asc') {
      direction = 'desc';
    }
    setSortConfig({ key, direction });
  };

  const sortedResults = React.useMemo(() => {
    let sortableItems = [...results];
    if (sortConfig !== null) {
      sortableItems.sort((a, b) => {
        const aValue = a[sortConfig.key];
        const bValue = b[sortConfig.key];

        if (aValue === bValue) return 0;
        if (aValue === undefined || aValue === null) return 1;
        if (bValue === undefined || bValue === null) return -1;

        if (aValue < bValue) {
          return sortConfig.direction === 'asc' ? -1 : 1;
        }
        if (aValue > bValue) {
          return sortConfig.direction === 'asc' ? 1 : -1;
        }
        return 0;
      });
    }
    return sortableItems;
  }, [results, sortConfig]);

  const startTest = (items: any[]) => {
    setIsTesting(true);
    if (wsRef.current) wsRef.current.close();

    const ws = new WebSocket(`${WS_BASE}/ws/test`);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('WS Connected');
      ws.send(JSON.stringify({ items }));
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'update') {
        setResults(prev => prev.map(item =>
          item.id === data.result.id ? { ...item, ...data.result, reference_answer: item.reference_answer } : item
        ));
        setStats(data.stats);
      } else if (data.type === 'complete') {
        setIsTesting(false);
        ws.close();
      } else if (data.type === 'error') {
        console.error('WS Error:', data.message);
        alert(`Error: ${data.message}`);
        setIsTesting(false);
      }
    };

    ws.onclose = () => {
      console.log('WS Disconnected');
      setIsTesting(false);
    };
  };

  const SortIcon = ({ column }: { column: keyof ResultItem }) => {
    if (sortConfig?.key !== column) return <span className="text-gray-400 ml-1">↕</span>;
    return <span className="ml-1">{sortConfig.direction === 'asc' ? '↑' : '↓'}</span>;
  };

  return (
    <div className="min-h-screen bg-gray-100 p-8 font-sans">
      <div className="max-w-7xl mx-auto">
        <header className="mb-8 flex justify-between items-center">
          <div>
            <h1 className="text-3xl font-bold text-gray-900">Zoo AI Voice Testing Dashboard</h1>
            <p className="text-gray-600">Real-time E2E Performance Monitoring</p>
          </div>
          <button
            onClick={() => setShowConfig(!showConfig)}
            className="px-4 py-2 bg-gray-200 rounded-md hover:bg-gray-300 text-gray-700"
          >
            {showConfig ? 'Hide Config' : 'STT Config'}
          </button>
        </header>

        {/* Error Banner */}
        {errorMsg && (
          <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded relative mb-4" role="alert">
            <strong className="font-bold">Error: </strong>
            <span className="block sm:inline">{errorMsg}</span>
            <span className="absolute top-0 bottom-0 right-0 px-4 py-3" onClick={() => setErrorMsg(null)}>
              <svg className="fill-current h-6 w-6 text-red-500" role="button" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><title>Close</title><path d="M14.348 14.849a1.2 1.2 0 0 1-1.697 0L10 11.819l-2.651 3.029a1.2 1.2 0 1 1-1.697-1.697l2.758-3.15-2.759-3.152a1.2 1.2 0 1 1 1.697-1.697L10 8.183l2.651-3.031a1.2 1.2 0 1 1 1.697 1.697l-2.758 3.152 2.758 3.15a1.2 1.2 0 0 1 0 1.698z" /></svg>
            </span>
          </div>
        )}

        {/* Config Panel */}
        {showConfig && (
          <div className="bg-white p-6 rounded-lg shadow mb-8 border border-blue-100">
            <h3 className="text-lg font-semibold mb-4">STT Phrase Hints (Fuzzy Matching)</h3>
            <div className="flex gap-2 mb-4">
              <input
                type="text"
                value={newHint}
                onChange={(e) => setNewHint(e.target.value)}
                placeholder="Add new phrase..."
                className="border rounded px-3 py-2 flex-grow"
                onKeyDown={(e) => e.key === 'Enter' && addHint()}
              />
              <button
                onClick={addHint}
                className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700"
              >
                Add
              </button>
            </div>
            <div className="flex flex-wrap gap-2">
              {phraseHints.map(hint => (
                <span key={hint} className="bg-blue-100 text-blue-800 px-3 py-1 rounded-full text-sm flex items-center gap-2">
                  {hint}
                  <button onClick={() => removeHint(hint)} className="hover:text-blue-900 font-bold">×</button>
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Control Panel */}
        <div className="bg-white p-6 rounded-lg shadow mb-8">
          <div className="flex items-center gap-4 mb-4">
            <div className="flex-grow">
              <input
                type="file"
                accept=".csv"
                onChange={handleFileChange}
                className="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
              />
            </div>

            {/* Language Selector */}
            <div className="flex items-center gap-2">
              <label className="text-sm font-medium text-gray-700">Language / STT:</label>
              <select
                value={sttProvider}
                onChange={(e) => setSttProvider(e.target.value)}
                className="border-gray-300 rounded-md shadow-sm p-2 border"
              >
                <option value="google">Chinese (Google STT)</option>
                <option value="openai">English (OpenAI Whisper)</option>
              </select>
            </div>
          </div>

          {/* Column Mapping */}
          {showMapping && (
            <div className="mb-4 p-4 bg-gray-50 rounded border border-gray-200">
              <h4 className="font-semibold mb-2">Column Mapping</h4>
              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700">ID Column</label>
                  <select
                    value={columnMapping.id}
                    onChange={(e) => setColumnMapping(prev => ({ ...prev, id: e.target.value }))}
                    className="mt-1 block w-full rounded-md border-gray-300 shadow-sm p-2 border"
                  >
                    <option value="">Select Column</option>
                    {availableColumns.map(col => <option key={col} value={col}>{col}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700">Question Column</label>
                  <select
                    value={columnMapping.question}
                    onChange={(e) => setColumnMapping(prev => ({ ...prev, question: e.target.value }))}
                    className="mt-1 block w-full rounded-md border-gray-300 shadow-sm p-2 border"
                  >
                    <option value="">Select Column</option>
                    {availableColumns.map(col => <option key={col} value={col}>{col}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700">Answer Column</label>
                  <select
                    value={columnMapping.answer}
                    onChange={(e) => setColumnMapping(prev => ({ ...prev, answer: e.target.value }))}
                    className="mt-1 block w-full rounded-md border-gray-300 shadow-sm p-2 border"
                  >
                    <option value="">Select Column</option>
                    {availableColumns.map(col => <option key={col} value={col}>{col}</option>)}
                  </select>
                </div>
              </div>
            </div>
          )}

          <div className="flex items-center gap-4">
            <button
              onClick={handleUpload}
              disabled={!file || isUploading || isTesting}
              className={`px-6 py-2 rounded-md text-white font-medium ${!file || isUploading || isTesting ? 'bg-gray-400 cursor-not-allowed' : 'bg-blue-600 hover:bg-blue-700'}`}
            >
              {isUploading ? 'Uploading...' : 'Upload & Process'}
            </button>

            {results.length > 0 && !isTesting && stats.processed === 0 && (
              <button
                onClick={handleStartTest}
                className="px-6 py-2 rounded-md text-white font-medium bg-green-600 hover:bg-green-700"
              >
                Generate Speech & Start Test
              </button>
            )}

            {isTesting && (
              <button
                onClick={handleStopTest}
                className="px-6 py-2 rounded-md text-white font-medium bg-red-600 hover:bg-red-700 flex items-center gap-2"
              >
                <span className="animate-pulse">●</span> Stop Test
              </button>
            )}

            {results.length > 0 && (
              <button
                onClick={handleExport}
                className="px-6 py-2 rounded-md text-white font-medium bg-gray-600 hover:bg-gray-700 ml-auto"
              >
                Export CSV
              </button>
            )}
          </div>
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
          <StatCard label="Progress" value={`${stats.processed} / ${stats.total}`} />
          <StatCard
            label="Avg Score"
            value={stats.avg_score.toFixed(1)}
            color={stats.avg_score >= 80 ? 'text-green-600' : stats.avg_score < 60 ? 'text-red-600' : 'text-yellow-600'}
          />
          <StatCard
            label="Avg Latency"
            value={`${stats.avg_latency.toFixed(2)}s`}
            color={stats.avg_latency <= 10 ? 'text-green-600' : 'text-red-600'}
          />
          <StatCard
            label="Success Rate (Score ≥ 80)"
            value={`${stats.processed > 0 ? ((results.filter(r => (r.score || 0) >= 80).length / stats.processed) * 100).toFixed(1) : 0}%`}
            color={stats.processed > 0 && (results.filter(r => (r.score || 0) >= 80).length / stats.processed) >= 0.8 ? 'text-green-600' : 'text-red-600'}
          />
        </div>

        {/* Results Table */}
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100" onClick={() => requestSort('id')}>
                  ID <SortIcon column="id" />
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Audio</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-1/6 cursor-pointer hover:bg-gray-100" onClick={() => requestSort('question')}>
                  Original Question <SortIcon column="question" />
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-1/6">Ref Answer</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-1/6">STT Output</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-1/6">AI Answer</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100" onClick={() => requestSort('score')}>
                  Score <SortIcon column="score" />
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100" onClick={() => requestSort('latency')}>
                  Latency (s) <SortIcon column="latency" />
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Breakdown</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {sortedResults.map((row, index) => (
                <tr
                  key={row.id}
                  style={{ backgroundColor: row.status === 'error' ? '#fef2f2' : index % 2 === 1 ? '#f3f4f6' : 'white' }}
                >
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{row.id}</td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    {row.audio_url ? (
                      <audio controls src={row.audio_url.startsWith('http') ? row.audio_url : `${API_BASE}${row.audio_url}`} className="h-8 w-32" />
                    ) : (
                      <span className="text-xs text-gray-400">Pending...</span>
                    )}
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-900">{row.question}</td>
                  <td className="px-6 py-4 text-sm text-gray-500">{row.reference_answer || '-'}</td>
                  <td className="px-6 py-4 text-sm text-gray-500 italic">{row.stt_text || '-'}</td>
                  <td className="px-6 py-4 text-sm text-gray-900">{row.status === 'error' ? row.error : (row.ai_answer || '-')}</td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    {row.score !== undefined ? (
                      <span className={`px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${row.score >= 80 ? 'bg-green-100 text-green-800' :
                        row.score < 60 ? 'bg-red-100 text-red-800' : 'bg-yellow-100 text-yellow-800'
                        }`}>
                        {row.score}
                      </span>
                    ) : '-'}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {row.latency ? `${row.latency.toFixed(2)}s` : '-'}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-xs text-gray-500">
                    {row.breakdown ? (
                      <>
                        <div>TTS: {row.breakdown.tts.toFixed(2)}s</div>
                        <div>STT: {row.breakdown.stt.toFixed(2)}s</div>
                        <div>Bot: {row.breakdown.chatbase.toFixed(2)}s</div>
                        <div>Eval: {row.breakdown.eval.toFixed(2)}s</div>
                      </>
                    ) : '-'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, color = 'text-gray-900' }: { label: string, value: string | number, color?: string }) {
  return (
    <div className="bg-white p-6 rounded-lg shadow">
      <dt className="text-sm font-medium text-gray-500 truncate">{label}</dt>
      <dd className={`mt-1 text-3xl font-semibold ${color}`}>{value}</dd>
    </div>
  );
}

export default App;
