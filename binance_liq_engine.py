import requests
import pandas as pd
import numpy as np
from scipy.signal import find_peaks
import json
import time
import sqlite3
import os
from datetime import datetime, timedelta

class LiquidationHeatmapEngine:
    def __init__(self, symbol='BTCUSDT'):
        self.symbol = symbol
        self.base_url = "https://fapi.binance.com"
        self.db_path = "market_data.db"  # Файл БД создастся в папке скрипта
        
        # Плечи (акцент на среднесрок, так как у нас теперь много данных)
        self.leverage_dist = {
            5: 0.05,    
            10: 0.15,   
            20: 0.25,
            25: 0.30,   
            50: 0.20,   
            100: 0.05   
        }
        
        # Полураспад увеличен до 3 дней, так как мы теперь видим историю за месяц
        self.half_life_hours = 72  

    def _init_db(self):
        """Создает таблицу, если её нет"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        # Храним свечи + OI в одной таблице
        c.execute('''CREATE TABLE IF NOT EXISTS market_history (
                        symbol TEXT,
                        timestamp INTEGER PRIMARY KEY,
                        open REAL, high REAL, low REAL, close REAL, volume REAL,
                        taker_buy_vol REAL,
                        oi REAL
                    )''')
        conn.commit()
        conn.close()

    def _save_to_db(self, df):
        """Сохраняет новые данные (Upsert)"""
        if df.empty: return
        
        conn = sqlite3.connect(self.db_path)
        # Преобразуем DF в список кортежей
        data = []
        for _, row in df.iterrows():
            ts = int(row['open_time'].timestamp() * 1000)
            data.append((
                self.symbol, ts, 
                row['open'], row['high'], row['low'], row['close'], row['volume'],
                row['taker_buy_base_vol'], row['sumOpenInterest']
            ))
        
        # INSERT OR REPLACE - обновляет данные, если такой timestamp уже есть
        conn.executemany('''INSERT OR REPLACE INTO market_history VALUES (?,?,?,?,?,?,?,?,?)''', data)
        conn.commit()
        conn.close()
        print(f"Saved {len(df)} candles to DB.")

    def _load_from_db(self, days=30):
        """Загружает историю за N дней"""
        conn = sqlite3.connect(self.db_path)
        cutoff = int((datetime.utcnow() - timedelta(days=days)).timestamp() * 1000)
        
        query = f"SELECT * FROM market_history WHERE symbol='{self.symbol}' AND timestamp > {cutoff} ORDER BY timestamp ASC"
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        if df.empty: return pd.DataFrame()
        
        # Восстанавливаем типы и имена колонок
        df['open_time'] = pd.to_datetime(df['timestamp'], unit='ms')
        df['sumOpenInterest'] = df['oi']
        df['taker_buy_base_vol'] = df['taker_buy_vol']
        # Остальные колонки уже называются правильно
        
        return df

    def fetch_and_update(self):
        """Качает свежее -> БД -> Возвращает полную историю"""
        self._init_db()
        
        print(f"[{self.symbol}] Updating data...")
        
        # 1. Качаем свежие данные (последние 5 дней, 15m)
        limit = 499
        interval = '15m' 
        
        try:
            # Klines
            r = requests.get(f"{self.base_url}/fapi/v1/klines", 
                             params={'symbol': self.symbol, 'interval': interval, 'limit': limit}, timeout=5)
            r.raise_for_status()
            raw_k = r.json()
            
            # OI
            r_oi = requests.get(f"{self.base_url}/futures/data/openInterestHist", 
                                params={'symbol': self.symbol, 'period': interval, 'limit': limit}, timeout=5)
            r_oi.raise_for_status()
            raw_oi = r_oi.json()
            
            # Сборка DF
            df_k = pd.DataFrame(raw_k, columns=['open_time', 'open', 'high', 'low', 'close', 'volume', 'ct', 'qav', 'nt', 'taker_buy_base_vol', 'tbqv', 'ig'])
            df_k = df_k[['open_time', 'open', 'high', 'low', 'close', 'volume', 'taker_buy_base_vol']].astype(float)
            df_k['open_time'] = pd.to_datetime(df_k['open_time'], unit='ms')
            
            df_oi = pd.DataFrame(raw_oi)
            df_oi['sumOpenInterest'] = df_oi['sumOpenInterest'].astype(float)
            df_oi['timestamp'] = pd.to_datetime(df_oi['timestamp'], unit='ms')
            
            # Merge
            df_k = df_k.sort_values('open_time')
            df_oi = df_oi.sort_values('timestamp')
            
            merged = pd.merge_asof(df_k, df_oi[['timestamp', 'sumOpenInterest']], 
                                   left_on='open_time', right_on='timestamp', 
                                   direction='nearest', tolerance=pd.Timedelta('15min'))
            
            merged = merged.dropna(subset=['sumOpenInterest'])
            
            # Сохраняем в БД
            self._save_to_db(merged)
            
        except Exception as e:
            print(f"API Update failed (using DB only): {e}")

        # 2. Читаем ПОЛНУЮ историю из БД (30 дней)
        full_df = self._load_from_db(days=30)
        print(f"Loaded {len(full_df)} candles from DB history.")
        return full_df

    def calculate_map(self, df):
        if df.empty: return [], [], [], 0
        
        # Логика расчета потоков (та же, что в V3)
        df['delta_oi'] = df['sumOpenInterest'].diff().fillna(0)
        df['oi_factor'] = np.maximum(df['delta_oi'], 0)
        mean_oi = df['sumOpenInterest'].mean()
        df['oi_factor'] = df['oi_factor'] / (mean_oi if mean_oi > 0 else 1)

        df['taker_sell_base_vol'] = df['volume'] - df['taker_buy_base_vol']
        total_vol = df['volume'].replace(0, 1)
        
        df['entry_vol_long'] = df['volume'] * (df['taker_buy_base_vol'] / total_vol) * df['oi_factor'] * 1000
        df['entry_vol_short'] = df['volume'] * (df['taker_sell_base_vol'] / total_vol) * df['oi_factor'] * 1000
        
        # Time Decay (с учетом увеличенного half_life)
        last_time = df['open_time'].max()
        df['age_hours'] = (last_time - df['open_time']).dt.total_seconds() / 3600
        df['time_weight'] = np.exp(-df['age_hours'] / self.half_life_hours)
        
        df['entry_vol_long_w'] = df['entry_vol_long'] * df['time_weight']
        df['entry_vol_short_w'] = df['entry_vol_short'] * df['time_weight']
        
        # Расчет карты
        current_price = df['close'].iloc[-1]
        price_step = 50
        # Широкий диапазон для поиска максимума (+/- 25%)
        bins = np.arange(current_price * 0.75, current_price * 1.25, price_step)
        liq_longs = np.zeros(len(bins))
        liq_shorts = np.zeros(len(bins))
        
        relevant = df[(df['entry_vol_long_w'] > 0.05) | (df['entry_vol_short_w'] > 0.05)]
        
        for _, row in relevant.iterrows():
            entry = row['close']
            if row['entry_vol_long_w'] > 0:
                for lev, w in self.leverage_dist.items():
                    liq = entry * (1 - 1/lev)
                    idx = int((liq - bins[0]) / price_step)
                    if 0 <= idx < len(bins): liq_longs[idx] += row['entry_vol_long_w'] * w
            
            if row['entry_vol_short_w'] > 0:
                for lev, w in self.leverage_dist.items():
                    liq = entry * (1 + 1/lev)
                    idx = int((liq - bins[0]) / price_step)
                    if 0 <= idx < len(bins): liq_shorts[idx] += row['entry_vol_short_w'] * w
                    
        return bins, liq_longs, liq_shorts, current_price

    def extract_clusters(self, bins, map_data, side, current_price, max_global_vol, top_n=5):
        if len(bins) == 0: return []
        peaks, _ = find_peaks(map_data, distance=20) # ~1000$ distance
        clusters = []
        limit_pct = 0.15 
        
        for p in peaks:
            price = bins[p]
            vol = map_data[p]
            
            if side == 'short' and price <= current_price: continue
            if side == 'long' and price >= current_price: continue
            
            dist_pct = abs(price - current_price) / current_price
            if dist_pct > limit_pct: continue
            
            rel_strength = vol / max_global_vol
            strength = int(np.ceil(rel_strength * 10))
            if strength > 10: strength = 10
            
            if rel_strength < 0.15: continue 
            
            # Комментарии
            if strength >= 9: desc = "Доминирующий пик ликвидности"
            elif strength >= 7: desc = "Крупный кластер стопов"
            elif strength >= 5: desc = "Заметное скопление"
            else: desc = "Небольшая зона"
            
            if dist_pct < 0.015: pos = "вплотную к текущей цене"
            elif dist_pct < 0.05: pos = "на ближайшем подходе"
            else: pos = "в среднесрочном диапазоне"
            
            end = "главный магнит для цены." if strength >= 7 else ("сильное сопротивление." if side == 'short' else "зона поддержки.")
            
            clusters.append({
                "price": int(price),
                "zone": [int(price - 100), int(price + 100)],
                "side": side,
                "strength": strength,
                "comment": f"{desc} {pos}. {end}",
                "vol": vol
            })
            
        return sorted(clusters, key=lambda x: x['vol'], reverse=True)[:top_n]

    def run(self):
        # Этап 1: Обновление и загрузка истории
        df = self.fetch_and_update()
        if df.empty: return json.dumps({"error": "No data available"})
        
        # Этап 2: Расчет
        bins, l_map, s_map, price = self.calculate_map(df)
        
        # Максимум
        max_total = max(np.max(l_map) if len(l_map)>0 else 1, np.max(s_map) if len(s_map)>0 else 1)
        
        l_cl = self.extract_clusters(bins, l_map, 'long', price, max_total)
        s_cl = self.extract_clusters(bins, s_map, 'short', price, max_total)
        
        for c in l_cl + s_cl: del c['vol']
        
        # Summary
        l_pow = sum(c['strength'] for c in l_cl[:3])
        s_pow = sum(c['strength'] for c in s_cl[:3])
        
        if s_pow > l_pow * 1.3: dom = "shorts"; comm = "Перевес ликвидности сверху (Short Squeeze)."
        elif l_pow > s_pow * 1.3: dom = "longs"; comm = "Давление на лонги снизу (Long Squeeze)."
        else: dom = "balanced"; comm = "Ликвидность сбалансирована."
        
        return json.dumps({
            "symbol": self.symbol,
            "source": "binance_db_history_v4",
            "captured_at_iso": datetime.utcnow().isoformat() + "Z",
            "captured_at_ms": int(time.time() * 1000),
            "current_price": int(price),
            "data_points": len(df), # Для отладки: сколько свечей в базе
            "zones": l_cl + s_cl,
            "summary": {
                "dominant_side": dom,
                "upside_focus_zone": f"{s_cl[0]['zone'][0]}-{s_cl[0]['zone'][1]}" if s_cl else None,
                "downside_focus_zone": f"{l_cl[0]['zone'][0]}-{l_cl[0]['zone'][1]}" if l_cl else None,
                "comment": comm
            }
        }, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    eng = LiquidationHeatmapEngine()
    print(eng.run())