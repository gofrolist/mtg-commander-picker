import React, { useState, useEffect } from 'react';
import './index.css';

const COLORS = ['White', 'Blue', 'Black', 'Red', 'Green'];

export default function App() {
  const [userName, setUserName] = useState('');
  const [started, setStarted] = useState(false);
  const [step, setStep] = useState(0);
  const [choices, setChoices] = useState([]);
  const [picked, setPicked] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const API_BASE = process.env.REACT_APP_API_URL || '/api/v1';

  useEffect(() => {
    if (!started || step >= COLORS.length) return;
    setLoading(true);
    setError(null);

    fetch(
      `${API_BASE}/cards/${encodeURIComponent(COLORS[step])}` +
      `?userName=${encodeURIComponent(userName)}`
    )
      .then((r) => {
        if (!r.ok) throw new Error('Failed to fetch cards');
        return r.json();
      })
      .then((cards) => {
        if (!Array.isArray(cards)) throw new Error('Invalid response');

        // If user already has all colors reserved, jump straight to final summary
        if (cards.length === COLORS.length) {
          setPicked(cards);
          setStep(COLORS.length);
          return;
        }
        // Auto-advance if this color already has exactly one reserved card
        if (cards.length === 1 && !picked.some(c => c.name === cards[0].name)) {
          setPicked(prev => [...prev, cards[0]]);
          setStep(s => s + 1);
        } else {
          setChoices(cards);
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [started, step, userName, API_BASE, picked]);

  const handlePick = (card) => {
    if (picked.some(c => c.name === card.name)) {
      setError(`You already have a ${COLORS[step]} card. Moving to the next color.`);
      setPicked(prev => [...prev, card]);
      setStep(s => s + 1);
      return;
    }

    setLoading(true);
    setError(null);

    fetch(`${API_BASE}/select-card`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ userName, cardName: card.name, cardColor: COLORS[step] }),
    })
      .then((r) => {
        if (r.status === 409) {
          setError(`You already reserved a ${COLORS[step]} card. Moving on.`);
          setPicked(prev => [...prev, card]);
          setStep(s => s + 1);
          return null;
        }
        if (!r.ok) return r.json().then(j => Promise.reject(j.message));
        return r.json();
      })
      .then((json) => {
        if (json) {
          setPicked(prev => [...prev, card]);
          setStep(s => s + 1);
        }
      })
      .catch((e) => setError(e && e.message ? e.message : String(e)))
      .finally(() => setLoading(false));
  };

  // Before anything, if we're loading a step, show loading
  if (started && loading) {
    return (
      <div className="p-8 text-center">
        <p>Loading...</p>
      </div>
    );
  }

  // Enter name form
  if (!started) {
    return (
      <div className="p-8 text-center">
        <h1 className="text-3xl font-bold mb-6">MTG Commander Picker</h1>
        <form
          className="flex flex-col items-center"
          onSubmit={e => { e.preventDefault(); if (userName.trim()) setStarted(true); }}
        >
          <input
            className="border p-3 rounded w-72 mb-4"
            value={userName}
            onChange={e => setUserName(e.target.value)}
            placeholder="Enter your name"
          />
          <button
            type="submit"
            className="bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2 px-6 rounded-lg transition transform hover:scale-105"
          >Start</button>
        </form>
      </div>
    );
  }

  // Final summary once all COLORS are picked, show responsive grid without names or button
  if (step >= COLORS.length) {
    return (
      <div className="p-8 text-center">
        <h2 className="text-2xl font-semibold mb-4">Here are your commanders:</h2>
        <div
          className="grid gap-6 justify-items-center"
          style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }}
        >
          {picked.map(card => (
            <div key={card.name} className="flex flex-col items-center" title={card.name}>
              <img
                src={card.image}
                alt={card.name}
                title={card.name}
                className="w-full h-auto object-cover rounded-lg shadow-md"
              />
            </div>
          ))}
        </div>
      </div>
    );
  }

  // Picker UI for current color
  return (
    <div className="p-8 text-center">
      <h1 className="text-3xl font-bold mb-6">Pick your {COLORS[step]} card</h1>
      {error && <p className="text-red-500 mb-4">{error}</p>}
      <div className="grid grid-cols-3 gap-6 justify-center">
        {choices.map(card => (
          <div
            key={card.name}
            className="bg-white rounded-xl shadow-md overflow-hidden cursor-pointer hover:shadow-lg transition transform hover:scale-105 p-4"
            onClick={() => handlePick(card)}
            title={card.name}
          >
            <img src={card.image} alt={card.name} className="w-full h-auto mb-2" />
          </div>
        ))}
      </div>
    </div>
  );
}