import React, { useState, useEffect } from 'react';
import './index.css';

// Draft picks in color order
const COLORS = ['White', 'Blue', 'Black', 'Red', 'Green'];

export default function App() {
  const [userName, setUserName] = useState('');
  const [started, setStarted] = useState(false);
  const [step, setStep] = useState(0);
  const [choices, setChoices] = useState([]);
  const [picked, setPicked] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const API_BASE = process.env.REACT_APP_API_URL || '/api';

  useEffect(() => {
    if (!started || step >= COLORS.length) return;
    setLoading(true);
    setError(null);

    fetch(`${API_BASE}/cards?color=${encodeURIComponent(COLORS[step])}`)
      .then((r) => {
        if (!r.ok) throw new Error('Failed to fetch cards');
        return r.json();
      })
      .then((cards) => {
        if (cards.length === 0) {
          setError(`No more ${COLORS[step]} cards available`);
        } else {
          setChoices(cards);
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [started, step]);

  const handlePick = (card) => {
    if (loading) return;
    setLoading(true);
    setError(null);

    fetch(`${API_BASE}/select-card`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        userName,
        cardName: card.name,
        cardColor: COLORS[step],
      }),
    })
      .then((r) => {
        if (!r.ok) return r.json().then((j) => Promise.reject(j.message));
        return r.json();
      })
      .then(() => {
        setPicked((p) => [...p, card]);
        setStep((s) => s + 1);
      })
      .catch((e) => setError(e))
      .finally(() => setLoading(false));
  };

  if (!started) {
    return (
      <div className="p-4 text-center">
        <h1 className="text-2xl mb-4">Enter Your Name</h1>
        <input
          className="border p-2 rounded w-64"
          value={userName}
          onChange={(e) => setUserName(e.target.value)}
          placeholder="Your name"
        />
        <button
          className="ml-2 bg-blue-500 text-white px-4 py-2 rounded"
          onClick={() => userName.trim() && setStarted(true)}
        >
          Start
        </button>
      </div>
    );
  }

  if (step >= COLORS.length) {
    return (
      <div className="p-4 text-center">
        <h1 className="text-2xl mb-4">Your Commanders</h1>
        <div className="flex flex-wrap justify-center gap-4">
          {picked.map((c) => (
            <div key={c.name} className="w-48">
              {c.image ? (
                <img
                  src={c.image}
                  alt={c.name}
                  className="w-full h-64 object-cover rounded"
                />
              ) : (
                <div className="h-64 flex items-center justify-center bg-gray-200">
                  No Image
                </div>
              )}
              <p className="mt-2 text-center font-semibold">{c.name}</p>
            </div>
          ))}
        </div>
        <button
          className="mt-6 bg-green-500 text-white px-4 py-2 rounded"
          onClick={() => {
            setStarted(false);
            setStep(0);
            setPicked([]);
          }}
        >
          Play Again
        </button>
      </div>
    );
  }

  const color = COLORS[step];

  return (
    <div className="p-4 text-center">
      <h1 className="text-2xl mb-4">Pick a {color} Commander</h1>

      {loading && <div className="loader mx-auto mb-4"></div>}

      {error && (
        <div className="text-red-600 mb-4">
          {error}
          <button className="block mt-2 underline" onClick={() => setStep(step)}>
            Retry
          </button>
        </div>
      )}

      {!loading && !error && (
        <div className="flex flex-wrap justify-center gap-4">
          {choices.map((card) => (
            <div
              key={card.name}
              className="cursor-pointer w-48 shadow rounded overflow-hidden hover:shadow-lg"
              onClick={() => handlePick(card)}
            >
              {card.image ? (
                <img
                  src={card.image}
                  alt={card.name}
                  className="w-full h-64 object-cover"
                />
              ) : (
                <div className="h-64 flex items-center justify-center bg-gray-200">
                  No Image
                </div>
              )}
              <p className="p-2 text-center font-medium">{card.name}</p>
            </div>
          ))}
        </div>
      )}

      {/* Spinner CSS */}
      <style>{`
        .loader {
          border: 4px solid #f3f3f3;
          border-top: 4px solid #3498db;
          border-radius: 50%;
          width: 40px;
          height: 40px;
          animation: spin 1s linear infinite;
          margin: 0 auto;
        }
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
