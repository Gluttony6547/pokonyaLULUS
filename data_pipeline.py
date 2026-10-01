"""
Data Pipeline Module for Hybrid Multimodal Stock Trading Signal Prediction Engine.
Fase 3 Implementation: Ingestion, Feature Extraction, Sentiment Pseudolabeling, and Temporal Fusion.

Based on research specifications (2026053141-1.pdf & Prompt V1.md):
- 19 Fused Features (14 Technical Indicators + 5 Sentiment Aggregates)
- Strict 16:00 WIB cut-off rule & weekend/holiday roll-forward aggregation to eliminate lookahead bias.
- Lexicon + SVM Pseudolabeling (confidence threshold 95% down to 80%).
"""

import datetime
import logging
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("DataPipeline")


class TechnicalIndicatorExtractor:
    """Extracts 14 technical indicators from basic OHLCV stock price data."""

    @staticmethod
    def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculates SMA (5,10,20,50), EMA (5,10,20,50), RSI (14),
        MACD (12,26,9), and Bollinger Bands (20, 2 STD).
        
        Expects df columns: ['open', 'high', 'low', 'close', 'volume']
        """
        df = df.copy()
        close = df['close']

        # Simple Moving Averages (SMA)
        df['sma_5'] = close.rolling(window=5).mean()
        df['sma_10'] = close.rolling(window=10).mean()
        df['sma_20'] = close.rolling(window=20).mean()
        df['sma_50'] = close.rolling(window=50).mean()

        # Exponential Moving Averages (EMA)
        df['ema_5'] = close.ewm(span=5, adjust=False).mean()
        df['ema_10'] = close.ewm(span=10, adjust=False).mean()
        df['ema_20'] = close.ewm(span=20, adjust=False).mean()
        df['ema_50'] = close.ewm(span=50, adjust=False).mean()

        # Relative Strength Index (RSI - 14)
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-10)
        df['rsi'] = 100 - (100 / (1 + rs))

        # MACD (12, 26, 9)
        ema_12 = close.ewm(span=12, adjust=False).mean()
        ema_26 = close.ewm(span=26, adjust=False).mean()
        df['macd'] = ema_12 - ema_26
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()

        # Bollinger Bands (20, 2 STD)
        ma_20 = close.rolling(window=20).mean()
        std_20 = close.rolling(window=20).std()
        df['middleband'] = ma_20
        df['upperband'] = ma_20 + (std_20 * 2)
        df['lowerband'] = ma_20 - (std_20 * 2)

        return df


class NewsTextPreprocessor:
    """Preprocesses Indonesian financial news titles for sentiment analysis."""

    def __init__(self):
        # Indonesian basic stopword list
        self.stopwords = set([
            "dan", "di", "ke", "dari", "ini", "itu", "yang", "untuk", "pada", "adalah",
            "dengan", "akan", "juga", "atau", "bisa", "tidak", "ada", "karena", "ia"
        ])

    def clean_text(self, text: str) -> str:
        """Applies case folding, special character removal, and tokenization."""
        if not isinstance(text, str):
            return ""
        # Case folding
        text = text.lower()
        # Remove numbers and special characters
        cleaned = "".join([char if char.isalnum() or char.isspace() else " " for char in text])
        # Remove extra whitespace & stopwords
        tokens = [word for word in cleaned.split() if word not in self.stopwords and len(word) > 2]
        return " ".join(tokens)


class SVMPseudolabeler:
    """Iterative Lexicon + SVM Pseudolabeling module (95% -> 80% confidence)."""

    def __init__(self, min_confidence: float = 0.80, step: float = 0.05):
        self.min_confidence = min_confidence
        self.step = step

    def pseudolabel(self, unlabelled_texts: List[str], initial_labelled: List[Tuple[str, int]]) -> pd.DataFrame:
        """
        Executes pseudolabeling iteration from 0.95 down to min_confidence threshold.
        Returns sentiment flags -1, 0, 1, or 2; samples below the confidence
        floor retain a missing flag instead of being assigned as neutral.
        """
        from sklearn.feature_extraction.text import CountVectorizer
        from sklearn.svm import SVC
        from scipy.sparse import vstack

        # 1. Vectorization
        vectorizer = CountVectorizer(max_features=5000, ngram_range=(1, 2))
        
        train_texts, train_labels = zip(*initial_labelled) if initial_labelled else ([], [])
        
        if not train_texts:
            logger.warning("No initial labeled seed provided; news remains unlabeled.")
            return pd.DataFrame({'text': unlabelled_texts, 'sentiment_flag': np.nan})

        X_train = vectorizer.fit_transform(train_texts)
        y_train = np.array(train_labels)

        X_unlabelled = vectorizer.transform(unlabelled_texts)
        if np.unique(y_train).size < 2:
            logger.warning("Pseudolabeling needs at least two seed classes; news remains unlabeled.")
            return pd.DataFrame({'text': unlabelled_texts, 'sentiment_flag': np.nan})

        unlabelled_indices = list(range(len(unlabelled_texts)))
        current_confidence = 0.95
        predictions = {}

        while current_confidence + 1e-9 >= self.min_confidence and unlabelled_indices:
            model = SVC(kernel='rbf', C=1.0, probability=True, random_state=42)
            model.fit(X_train, y_train)

            X_curr = X_unlabelled[unlabelled_indices]
            probs = model.predict_proba(X_curr)
            max_probs = np.max(probs, axis=1)
            pred_labels = model.classes_[np.argmax(probs, axis=1)]

            high_conf_mask = max_probs >= current_confidence
            if not np.any(high_conf_mask):
                current_confidence -= self.step
                continue

            high_conf_idx = [unlabelled_indices[i] for i in range(len(unlabelled_indices)) if high_conf_mask[i]]
            high_conf_labels = pred_labels[high_conf_mask]
            for orig_i, label in zip(high_conf_idx, high_conf_labels):
                predictions[orig_i] = label

            X_train = vstack((X_train, X_unlabelled[high_conf_idx]))
            y_train = np.concatenate((y_train, high_conf_labels))
            unlabelled_indices = [idx for idx in unlabelled_indices if idx not in predictions]
            current_confidence -= self.step

        final_flags = [predictions.get(i, np.nan) for i in range(len(unlabelled_texts))]
        return pd.DataFrame({'text': unlabelled_texts, 'sentiment_flag': final_flags})


class TemporalDataFuser:
    """
    Fuses technical stock data and news sentiment without lookahead bias.
    Applies the 16:00 WIB cut-off rule and holiday/weekend aggregation.
    """

    @staticmethod
    def adjust_news_trading_date(published_at: pd.Timestamp) -> pd.Timestamp:
        """
        Applies 16:00 WIB cut-off rule:
        If news is published AFTER 16:00 WIB, roll forward to next day.
        If next day is weekend (Saturday/Sunday), roll forward to Monday.
        """
        dt = pd.to_datetime(published_at)
        
        # Cut-off 16:00 WIB check
        if dt.hour >= 16:
            dt = dt + pd.Timedelta(days=1)
            
        # Weekend check
        while dt.weekday() >= 5: # 5=Saturday, 6=Sunday
            dt = dt + pd.Timedelta(days=1)
            
        return dt.normalize()

    @classmethod
    def fuse_multimodal_data(
        cls, 
        stock_df: pd.DataFrame, 
        news_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Performs Outer Merge on 'datetime' date, aggregates news sentiment by date,
        and fills NaN values appropriately to construct 19 predictor features.
        """
        stock_df = stock_df.copy()
        stock_df['datetime'] = pd.to_datetime(stock_df['datetime']).dt.normalize()

        if not news_df.empty:
            news_df = news_df.copy()
            news_df['trading_date'] = news_df['published_at'].apply(cls.adjust_news_trading_date)

            # Aggregate daily news sentiment
            sentiment_summary = news_df.groupby('trading_date').agg(
                negative_count=('sentiment_flag', lambda s: (s == -1).sum()),
                positive_count=('sentiment_flag', lambda s: (s == 2).sum()),
                neutral_count=('sentiment_flag', lambda s: (s == 0).sum()),
                total_news=('sentiment_flag', 'count'),
                sentiment=('sentiment_flag', lambda s: (
                    2 if (s == 2).sum() > (s == -1).sum() else (
                        -1 if (s == -1).sum() > (s == 2).sum() else (
                            1 if (s == 2).sum() == (s == -1).sum() and (s == 2).sum() > 0 else 0
                        )
                    )
                ))
            ).reset_index()
            
            sentiment_summary.rename(columns={'trading_date': 'datetime'}, inplace=True)

            # Outer Merge by datetime
            fused_df = pd.merge(stock_df, sentiment_summary, on='datetime', how='left')
        else:
            fused_df = stock_df.copy()
            fused_df['negative_count'] = 0
            fused_df['positive_count'] = 0
            fused_df['neutral_count'] = 0
            fused_df['total_news'] = 0
            fused_df['sentiment'] = 0 # Default no sentiment

        # Fill missing sentiment values for trading days without news
        fused_df['negative_count'] = fused_df['negative_count'].fillna(0).astype(int)
        fused_df['positive_count'] = fused_df['positive_count'].fillna(0).astype(int)
        fused_df['neutral_count'] = fused_df['neutral_count'].fillna(0).astype(int)
        fused_df['total_news'] = fused_df['total_news'].fillna(0).astype(int)
        fused_df['sentiment'] = fused_df['sentiment'].fillna(0).astype(int)

        # Drop non-trading rows where stock price is NaN
        fused_df = fused_df.dropna(subset=['close']).reset_index(drop=True)

        return fused_df


def generate_sample_fused_dataset() -> pd.DataFrame:
    """Helper utility to generate mock fused data for testing pipeline flow."""
    dates = pd.date_range(end=datetime.date.today(), periods=100, freq='B')
    
    np.random.seed(42)
    base_price = 1500 + np.cumsum(np.random.randn(100) * 15)
    
    raw_stock = pd.DataFrame({
        'datetime': dates,
        'symbol': 'ADRO',
        'open': base_price + np.random.randn(100) * 5,
        'high': base_price + np.abs(np.random.randn(100) * 10),
        'low': base_price - np.abs(np.random.randn(100) * 10),
        'close': base_price,
        'volume': np.random.randint(1000000, 50000000, size=100)
    })

    # Compute 14 technical indicators
    stock_with_tech = TechnicalIndicatorExtractor.compute_indicators(raw_stock)

    # Mock news
    mock_news = pd.DataFrame({
        'published_at': [
            pd.Timestamp(dates[10]) + pd.Timedelta(hours=10), # Before 16:00
            pd.Timestamp(dates[10]) + pd.Timedelta(hours=17), # After 16:00 -> rolls to dates[11]
            pd.Timestamp(dates[25]) + pd.Timedelta(hours=14),
        ],
        'sentiment_flag': [2, -1, 2] # Positive, Negative, Positive
    })

    fused_dataset = TemporalDataFuser.fuse_multimodal_data(stock_with_tech, mock_news)
    return fused_dataset


if __name__ == "__main__":
    logger.info("Executing Data Pipeline test run...")
    fused_data = generate_sample_fused_dataset()
    logger.info(f"Successfully generated fused dataset with shape: {fused_data.shape}")
    logger.info(f"Columns ({len(fused_data.columns)} total): {list(fused_data.columns)}")
    print(fused_data.tail(5)[['datetime', 'symbol', 'close', 'sma_50', 'rsi', 'macd', 'sentiment']])
