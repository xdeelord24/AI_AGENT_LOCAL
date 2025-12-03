import React, { useMemo } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer
} from 'recharts';
import { TrendingUp, TrendingDown, Minus } from 'lucide-react';

// Deterministic random number generator based on seed
const seededRandom = (seed) => {
  let value = seed;
  return () => {
    value = (value * 9301 + 49297) % 233280;
    return value / 233280;
  };
};

const PriceChart = ({ priceData, assetName, assetType = 'crypto' }) => {
  // Generate sample historical data if not provided
  const chartData = useMemo(() => {
    if (priceData && Array.isArray(priceData) && priceData.length > 0) {
      return priceData;
    }
    
    // Generate sample data based on current price
    const currentPrice = priceData?.currentPrice || priceData?.price || 0;
    if (!currentPrice || currentPrice === 0) return null;
    
    // Use timestamp from price_data if available, otherwise use current time
    // This ensures the same historical data is generated when restoring chats
    const baseTimestamp = priceData?.timestamp 
      ? new Date(priceData.timestamp).getTime() 
      : Date.now();
    const baseDate = new Date(baseTimestamp);
    
    // Create a deterministic seed from timestamp and price
    // This ensures the same data is generated for the same timestamp+price combination
    const seed = Math.floor(baseTimestamp / 1000) + Math.floor(currentPrice * 100);
    const random = seededRandom(seed);
    
    const data = [];
    const volatility = assetType === 'forex' ? 0.02 : 0.05; // Lower volatility for forex
    
    for (let i = 29; i >= 0; i--) {
      const date = new Date(baseDate);
      date.setDate(date.getDate() - i);
      
      // Generate deterministic price movement based on seed
      const randomChange = (random() - 0.5) * volatility;
      const price = currentPrice * (1 + randomChange * (30 - i) / 30);
      
      data.push({
        date: date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
        price: parseFloat(price.toFixed(assetType === 'forex' ? 4 : 2)),
        timestamp: date.getTime()
      });
    }
    
    return data;
  }, [priceData, assetType]);

  if (!chartData || chartData.length === 0) {
    return null;
  }

  const currentPrice = chartData[chartData.length - 1]?.price || chartData[0]?.price || 0;
  const previousPrice = chartData.length > 1 ? chartData[chartData.length - 2]?.price : currentPrice;
  const priceChange = currentPrice - previousPrice;
  const priceChangePercent = previousPrice !== 0 ? ((priceChange / previousPrice) * 100).toFixed(2) : 0;
  const isPositive = priceChange >= 0;

  const formatPrice = (value) => {
    if (assetType === 'forex') {
      return value.toFixed(4);
    }
    if (value >= 1000) {
      return `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }
    return `$${value.toFixed(2)}`;
  };

  const CustomTooltip = ({ active, payload }) => {
    if (active && payload && payload.length) {
      return (
        <div className="bg-dark-800 border border-dark-600 rounded-lg p-3 shadow-lg">
          <p className="text-xs text-dark-400 mb-1">{payload[0].payload.date}</p>
          <p className="text-sm font-semibold text-dark-100">
            {formatPrice(payload[0].value)}
          </p>
        </div>
      );
    }
    return null;
  };

  return (
    <div className="mt-4 rounded-lg border border-dark-600 bg-dark-800/50 p-4">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-dark-200 mb-1">
            {assetName || 'Price Chart'}
          </h3>
          <div className="flex items-center gap-3">
            <span className="text-lg font-bold text-dark-100">
              {formatPrice(currentPrice)}
            </span>
            <div className={`flex items-center gap-1 text-xs ${
              isPositive ? 'text-emerald-400' : priceChange < 0 ? 'text-red-400' : 'text-dark-400'
            }`}>
              {isPositive ? (
                <TrendingUp className="w-3 h-3" />
              ) : priceChange < 0 ? (
                <TrendingDown className="w-3 h-3" />
              ) : (
                <Minus className="w-3 h-3" />
              )}
              <span>
                {isPositive ? '+' : ''}{formatPrice(Math.abs(priceChange))} ({isPositive ? '+' : ''}{priceChangePercent}%)
              </span>
            </div>
          </div>
        </div>
        <div className="text-xs text-dark-400">
          Last 30 days
        </div>
      </div>
      
      <ResponsiveContainer width="100%" height={250}>
        <AreaChart data={chartData} margin={{ top: 5, right: 5, left: 5, bottom: 5 }}>
          <defs>
            <linearGradient id="colorPrice" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={isPositive ? "#10b981" : "#ef4444"} stopOpacity={0.3}/>
              <stop offset="95%" stopColor={isPositive ? "#10b981" : "#ef4444"} stopOpacity={0}/>
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis 
            dataKey="date" 
            stroke="#9ca3af"
            fontSize={10}
            tick={{ fill: '#9ca3af' }}
            interval="preserveStartEnd"
          />
          <YAxis 
            stroke="#9ca3af"
            fontSize={10}
            tick={{ fill: '#9ca3af' }}
            tickFormatter={formatPrice}
            domain={['auto', 'auto']}
          />
          <Tooltip content={<CustomTooltip />} />
          <Area
            type="monotone"
            dataKey="price"
            stroke={isPositive ? "#10b981" : "#ef4444"}
            strokeWidth={2}
            fillOpacity={1}
            fill="url(#colorPrice)"
          />
        </AreaChart>
      </ResponsiveContainer>
      
      {/* Additional Analytics */}
      <div className="mt-4 grid grid-cols-3 gap-4 pt-4 border-t border-dark-700">
        <div>
          <div className="text-xs text-dark-400 mb-1">24h High</div>
          <div className="text-sm font-semibold text-dark-200">
            {formatPrice(Math.max(...chartData.slice(-24).map(d => d.price)))}
          </div>
        </div>
        <div>
          <div className="text-xs text-dark-400 mb-1">24h Low</div>
          <div className="text-sm font-semibold text-dark-200">
            {formatPrice(Math.min(...chartData.slice(-24).map(d => d.price)))}
          </div>
        </div>
        <div>
          <div className="text-xs text-dark-400 mb-1">30d Avg</div>
          <div className="text-sm font-semibold text-dark-200">
            {formatPrice(chartData.reduce((sum, d) => sum + d.price, 0) / chartData.length)}
          </div>
        </div>
      </div>
    </div>
  );
};

export default PriceChart;

