"""
Phase 4: Model Development & Training Engine
Hybrid Stock Trading Signal Prediction Using Multimodal Ensemble Learning
"""

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.ensemble import RandomForestClassifier, AdaBoostClassifier
from sklearn.svm import SVC
from sklearn.neighbors import KNeighborsClassifier
from xgboost import XGBClassifier
from sklearn.preprocessing import StandardScaler, LabelEncoder
from scipy.stats import mode
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Set Seed for Reproducibility
SEED = 42
np.random.seed(SEED)
torch.manual_seed(SEED)

# ==========================================
# 1. PyTorch Deep Learning Architectures
# ==========================================

class LSTMRegressor(nn.Module):
    """Path 1: LSTM Price Regression Model"""
    def __init__(self, input_dim, hidden_dim=96, num_layers=3, dropout=0.20):
        super(LSTMRegressor, self).__init__()
        self.lstm = nn.LSTM(input_dim, hidden_dim, num_layers=num_layers, 
                            batch_first=True, dropout=dropout if num_layers > 1 else 0)
        self.fc = nn.Linear(hidden_dim, 1)

    def forward(self, x):
        out, _ = self.lstm(x)
        out = self.fc(out[:, -1, :])
        return out.squeeze(-1)

class RecurrentClassifier(nn.Module):
    """Path 3: Deep Learning Classifier (LSTM, BiLSTM, GRU, BiGRU)"""
    def __init__(self, cell_type, input_dim, hidden_dim=96, num_layers=3, num_classes=3, dropout=0.20):
        super(RecurrentClassifier, self).__init__()
        self.cell_type = cell_type.lower()
        self.bidirectional = 'bi' in self.cell_type
        
        if 'gru' in self.cell_type:
            self.rnn = nn.GRU(input_dim, hidden_dim, num_layers=num_layers, batch_first=True,
                              dropout=dropout if num_layers > 1 else 0, bidirectional=self.bidirectional)
        else:
            self.rnn = nn.LSTM(input_dim, hidden_dim, num_layers=num_layers, batch_first=True,
                               dropout=dropout if num_layers > 1 else 0, bidirectional=self.bidirectional)
            
        fc_input_dim = hidden_dim * 2 if self.bidirectional else hidden_dim
        self.fc = nn.Linear(fc_input_dim, num_classes)

    def forward(self, x):
        out, _ = self.rnn(x)
        out = self.fc(out[:, -1, :])
        return out

# ==========================================
# 2. 3-Path Hybrid Ensemble Engine
# ==========================================

class HybridEnsembleEngine:
    """
    3-Path Multimodal Ensemble Learning Engine
    Path 1: LSTM Price Regression
    Path 2: ML Voting Classifier (RF, AdaBoost, XGB, SVM, KNN)
    Path 3: DL Voting Classifier (LSTM, BiLSTM, GRU, BiGRU)
    Final: Majority Voting Mechanism
    """
    def __init__(self, horizon_days=50, return_threshold=0.11):
        self.horizon_days = horizon_days
        self.return_threshold = return_threshold
        self.scaler = StandardScaler()
        self.label_encoder = LabelEncoder()
        
        # Path 1
        self.path1_model = None
        
        # Path 2 Models
        self.path2_models = {
            'rf': RandomForestClassifier(n_estimators=100, random_state=SEED, class_weight='balanced'),
            'adaboost': AdaBoostClassifier(n_estimators=50, learning_rate=1.0, random_state=SEED),
            'xgb': XGBClassifier(n_estimators=100, learning_rate=0.1, max_depth=6, random_state=SEED),
            'svm': SVC(C=1.0, kernel='rbf', probability=True, random_state=SEED),
            'knn': KNeighborsClassifier(n_neighbors=5, weights='distance')
        }
        
        # Path 3 Model Configs
        self.path3_cell_types = ['lstm', 'bilstm', 'gru', 'bigru']
        self.path3_models = {}

    def prepare_sequences(self, df_fused, feature_cols, window_size=50):
        """Build sliding window sequences for Deep Learning models"""
        X_seq, y_price, y_class = [], [], []
        
        # Calculate target classification labels based on future 50-day return
        df_fused['future_close'] = df_fused['close'].shift(-self.horizon_days)
        df_fused['return_50d'] = (df_fused['future_close'] - df_fused['close']) / df_fused['close']
        
        # Categorize Target: 0 (Sell <-11%), 1 (Hold -11% to +11%), 2 (Buy >+11%)
        def label_signal(ret):
            if ret > self.return_threshold:
                return 2  # Buy
            elif ret < -self.return_threshold:
                return 0  # Sell
            else:
                return 1  # Hold
                
        df_fused['target_signal'] = df_fused['return_50d'].apply(label_signal)
        df_clean = df_fused.dropna().reset_index(drop=True)
        
        scaled_features = self.scaler.fit_transform(df_clean[feature_cols])
        
        for i in range(len(df_clean) - window_size + 1):
            X_seq.append(scaled_features[i:i + window_size])
            y_price.append(df_clean.loc[i + window_size - 1, 'future_close'])
            y_class.append(df_clean.loc[i + window_size - 1, 'target_signal'])
            
        return np.array(X_seq), np.array(y_price), np.array(y_class), df_clean

    def train_path1(self, X_seq_train, y_price_train, epochs=30, batch_size=32):
        """Train Path 1: LSTM Price Regression"""
        input_dim = X_seq_train.shape[2]
        self.path1_model = LSTMRegressor(input_dim=input_dim)
        optimizer = torch.optim.Adam(self.path1_model.parameters(), lr=1e-3)
        criterion = nn.MSELoss()
        
        dataset = TensorDataset(torch.tensor(X_seq_train, dtype=torch.float32), 
                                torch.tensor(y_price_train, dtype=torch.float32))
        loader = DataLoader(dataset, batch_size=batch_size, shuffle=False)
        
        self.path1_model.train()
        for epoch in range(epochs):
            for batch_x, batch_y in loader:
                optimizer.zero_grad()
                pred = self.path1_model(batch_x)
                loss = criterion(pred, batch_y)
                loss.backward()
                optimizer.step()
        logging.info("Path 1 (LSTM Regression) Training Complete.")

    def train_path2(self, X_flat_train, y_class_train):
        """Train Path 2: Machine Learning Voting Classifiers"""
        # Ensure label encoding for XGBoost
        y_encoded = self.label_encoder.fit_transform(y_class_train)
        for name, model in self.path2_models.items():
            if name == 'xgb':
                model.fit(X_flat_train, y_encoded)
            else:
                model.fit(X_flat_train, y_class_train)
        logging.info("Path 2 (ML Voting Classifiers) Training Complete.")

    def train_path3(self, X_seq_train, y_class_train, epochs=30, batch_size=32):
        """Train Path 3: Deep Learning Voting Classifiers"""
        input_dim = X_seq_train.shape[2]
        dataset = TensorDataset(torch.tensor(X_seq_train, dtype=torch.float32), 
                                torch.tensor(y_class_train, dtype=torch.long))
        loader = DataLoader(dataset, batch_size=batch_size, shuffle=False)
        
        for cell_type in self.path3_cell_types:
            model = RecurrentClassifier(cell_type=cell_type, input_dim=input_dim)
            optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
            criterion = nn.CrossEntropyLoss()
            
            model.train()
            for epoch in range(epochs):
                for batch_x, batch_y in loader:
                    optimizer.zero_grad()
                    pred = model(batch_x)
                    loss = criterion(pred, batch_y)
                    loss.backward()
                    optimizer.step()
            self.path3_models[cell_type] = model
        logging.info("Path 3 (DL Voting Classifiers) Training Complete.")

    def predict_signals(self, X_seq_test, current_prices):
        """Execute 3-Path Prediction & Majority Voting"""
        # Path 1 Inference
        self.path1_model.eval()
        with torch.no_grad():
            pred_prices = self.path1_model(torch.tensor(X_seq_test, dtype=torch.float32)).numpy().reshape(-1)
            
        curr_p = np.array(current_prices).reshape(-1)
        p1_returns = (pred_prices - curr_p) / curr_p
        p1_signals = np.where(p1_returns > self.return_threshold, 2, 
                              np.where(p1_returns < -self.return_threshold, 0, 1)).reshape(-1)
        
        # Path 2 Inference (Flattened last step)
        X_flat_test = X_seq_test[:, -1, :]
        p2_preds = []
        for name, model in self.path2_models.items():
            if name == 'xgb':
                preds = model.predict(X_flat_test)
                preds = self.label_encoder.inverse_transform(preds)
            else:
                preds = model.predict(X_flat_test)
            p2_preds.append(preds)
        p2_signals = mode(np.array(p2_preds), axis=0).mode.reshape(-1)
        
        # Path 3 Inference
        p3_preds = []
        for model in self.path3_models.values():
            model.eval()
            with torch.no_grad():
                logits = model(torch.tensor(X_seq_test, dtype=torch.float32))
                preds = torch.argmax(logits, dim=1).numpy()
                p3_preds.append(preds)
        p3_signals = mode(np.array(p3_preds), axis=0).mode.reshape(-1)
        
        # Final Majority Voting across 3 Paths
        all_paths = np.vstack([p1_signals, p2_signals, p3_signals])
        final_signals = mode(all_paths, axis=0).mode.reshape(-1)
        
        return {
            'path1_signal': p1_signals,
            'path2_signal': p2_signals,
            'path3_signal': p3_signals,
            'final_ensemble_signal': final_signals,
            'predicted_prices': pred_prices
        }

# ==========================================
# 3. Execution Verification Pipeline
# ==========================================

if __name__ == "__main__":
    logging.info("Executing Phase 4 Training Engine Verification...")
    
    # Generate Synthetic Fused Multimodal Dataset (150 days)
    np.random.seed(SEED)
    n_days = 150
    dates = pd.date_range("2026-01-01", periods=n_days)
    
    close_prices = 1000 + np.cumsum(np.random.normal(2, 10, n_days))
    df_synthetic = pd.DataFrame({
        'datetime': dates,
        'symbol': 'ADRO',
        'close': close_prices,
        'sma_5': close_prices * 0.99,
        'sma_10': close_prices * 0.98,
        'sma_20': close_prices * 0.97,
        'sma_50': close_prices * 0.95,
        'ema_5': close_prices * 0.99,
        'ema_10': close_prices * 0.98,
        'ema_20': close_prices * 0.97,
        'ema_50': close_prices * 0.95,
        'rsi': np.random.uniform(30, 70, n_days),
        'macd': np.random.normal(0, 2, n_days),
        'macd_signal': np.random.normal(0, 2, n_days),
        'middleband': close_prices,
        'upperband': close_prices * 1.02,
        'lowerband': close_prices * 0.98,
        'negative_count': np.random.randint(0, 5, n_days),
        'positive_count': np.random.randint(0, 5, n_days),
        'neutral_count': np.random.randint(0, 5, n_days),
        'total_news': np.random.randint(1, 10, n_days),
        'sentiment': np.random.choice([-1, 0, 1, 2], n_days)
    })
    
    feature_cols = ['sma_5', 'sma_10', 'sma_20', 'sma_50', 'ema_5', 'ema_10', 'ema_20', 'ema_50',
                    'rsi', 'macd', 'macd_signal', 'middleband', 'upperband', 'lowerband',
                    'negative_count', 'positive_count', 'neutral_count', 'total_news', 'sentiment']
    
    engine = HybridEnsembleEngine(horizon_days=20, return_threshold=0.05)
    X_seq, y_price, y_class, df_clean = engine.prepare_sequences(df_synthetic, feature_cols, window_size=20)
    
    # Train-Test Split (80/20 Chronological)
    split_idx = int(len(X_seq) * 0.8)
    X_train, X_test = X_seq[:split_idx], X_seq[split_idx:]
    yp_train, yp_test = y_price[:split_idx], y_price[split_idx:]
    yc_train, yc_test = y_class[:split_idx], y_class[split_idx:]
    
    X_flat_train = X_train[:, -1, :]
    X_flat_test = X_test[:, -1, :]
    
    # Fit Models
    engine.train_path1(X_train, yp_train, epochs=5)
    engine.train_path2(X_flat_train, yc_train)
    engine.train_path3(X_train, yc_train, epochs=5)
    
    # Predict
    current_prices_test = df_clean.loc[split_idx + 19:, 'close'].values[:len(X_test)]
    results = engine.predict_signals(X_test, current_prices_test)
    
    logging.info(f"Phase 4 Execution Test Successful!")
    logging.info(f"Test Samples: {len(X_test)}")
    logging.info(f"Path 1 Signals: {results['path1_signal'][:5]}")
    logging.info(f"Path 2 Signals: {results['path2_signal'][:5]}")
    logging.info(f"Path 3 Signals: {results['path3_signal'][:5]}")
    logging.info(f"Final Majority Signals: {results['final_ensemble_signal'][:5]}")
