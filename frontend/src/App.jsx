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
        setPicked((prev) => [...prev, card]);
        setStep((s) => s + 1);
      })
      .catch((e) => setError(e))
      .finally(() => setLoading(false));
  };

  if (!started) {
    return (
      <div className="p-8 text-center">
        <h1 className="text-3xl font-bold mb-6">MTG Commander Picker</h1>
        <form
          className="flex flex-col items-center"
          onSubmit={(e) => {
            e.preventDefault();
            if (userName.trim()) setStarted(true);
          }}
        >
          <input
            className="border p-3 rounded w-72 mb-4"
            value={userName}
            onChange={(e) => setUserName(e.target.value)}
            placeholder="Enter your name"
          />
          <button
            type="submit"
            className="bg-blue-600 text-white px-6 py-3 rounded hover:bg-blue-700"
          >
            Start
          </button>
        </form>
      </div>
    );
  }

  const color = COLORS[step];
  const isFinished = step >= COLORS.length;

  return (
    <div className="p-8 text-center font-sans">
      <h1 className="text-3xl font-bold mb-6">MTG Commander Picker</h1>

      {!isFinished && (
        <>
          <h2 className="text-2xl font-semibold mb-4">
            Choose a Commander for: <span className="text-blue-600">{color}</span>
          </h2>

          {loading ? (
            <div className="text-gray-600 text-lg">Loading cards...</div>
          ) : error ? (
            <div className="text-red-600">
              {error}
              <br />
              <button className="mt-2 underline" onClick={() => setStep(step)}>
                Retry
              </button>
            </div>
          ) : (
            <div className="flex flex-wrap justify-center gap-6 px-4"> {/* Flexbox container for choices with reduced card width */}
              {choices.map((card) => (
                <div
                  key={card.name}
                  className="bg-white rounded-xl shadow-md overflow-hidden w-48 cursor-pointer hover:shadow-lg transition duration-300 transform hover:scale-105" /* Card container with rounded corners and overflow hidden */
                  onClick={() => handlePick(card)}
                >
                  {card.image ? (
                    <img
                      src={card.image}
                      alt={card.name}
                      className="w-full h-auto object-cover"
                      style={{ display: 'block' }} // avoids inline spacing issue
                      draggable={false}
                    />
                  ) : (
                    <div className="w-full h-80 flex items-center justify-center bg-gray-200 text-gray-600 rounded-md"> {/* Rounded corners for placeholder */}
                      No Image
                    </div>
                  )}
                  <p className="p-2 text-center font-medium">{card.name}</p>
                </div>
              ))}
            </div>

          )}
        </>
      )}

      {isFinished && (
        <div className="text-center">
          <h2 className="text-2xl font-semibold mb-4">Your Chosen Commanders:</h2>
          <div className="flex flex-wrap justify-center gap-4"> {/* Flexbox container for picked cards with reduced card width */}
            {picked.map((card) => (
              <div
                key={card.name}
                className="bg-green-100 rounded-lg shadow-md overflow-hidden w-48" /* Card container with rounded corners and overflow hidden */
              >
                {card.image ? (
                  <img src={card.image} alt={card.name} className="w-full h-auto object-cover" />
                ) : (
                  <div className="w-full h-80 flex items-center justify-center bg-gray-200 text-gray-600 rounded-md"> {/* Rounded corners for placeholder */}
                    No Image
                  </div>
                )}
                <p className="p-2 font-semibold">{card.name}</p>
              </div>
            ))}
          </div>
          <button
            className="mt-8 bg-blue-600 hover:bg-blue-700 text-white font-bold py-2 px-6 rounded-lg shadow-lg transition transform hover:scale-105"
            onClick={() => {
              setStarted(false);
              setStep(0);
              setPicked([]);
              setChoices([]);
            }}
          >
            Start Over
          </button>
        </div>
      )}
    </div>
  );
}