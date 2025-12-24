"""Report generation module."""

from datetime import datetime, timezone
from typing import Literal, Optional

from .analyze import AnalysisResult, CompareResult, LiquidationLevel


DISCLAIMER_EN = """
---
**⚠️ DISCLAIMER**: This analysis is for informational purposes only and does not constitute investment advice. 
Cryptocurrency trading involves substantial risk. Past performance is not indicative of future results. 
Always conduct your own research before making any trading decisions.
"""

DISCLAIMER_ZH = """
---
**⚠️ 免责声明**：本分析仅供参考，不构成任何投资建议。
加密货币交易存在重大风险。过往表现不代表未来收益。
请在做出任何交易决策前进行独立研究。
"""

TEMPLATE_EN = """# {symbol} Liquidation Heatmap Analysis

**Source**: {source} | **Timeframe**: {timeframe}  
**Captured**: {captured_at}  
**Current Price**: ${current_price:,.2f}  
**Analysis Mode**: {mode_used}  
**Overall Confidence**: {confidence:.1%}

---

## 🔥 Key Liquidation Levels

{levels_section}

---

## 📊 Analysis Summary

{summary}

---

## ⚡ Potential Price Magnet Paths

{magnet_paths}

---

## ⚠️ Risk Factors

{risk_factors}

{disclaimer}
"""

TEMPLATE_ZH = """# {symbol} 清算热力图分析

**数据源**: {source} | **时间周期**: {timeframe}  
**截图时间**: {captured_at}  
**当前价格**: ${current_price:,.2f}  
**分析模式**: {mode_used}  
**整体置信度**: {confidence:.1%}

---

## 🔥 关键清算区间

{levels_section}

---

## 📊 分析总结

{summary}

---

## ⚡ 潜在价格磁吸路径

{magnet_paths}

---

## ⚠️ 风险提示

{risk_factors}

{disclaimer}
"""


def generate_report(
    result: AnalysisResult | CompareResult,
    source: str,
    symbol: str,
    timeframe: str,
    language: Literal["zh", "en"] = "zh",
    captured_at: Optional[str] = None,
) -> str:
    """
    Generate a Markdown report from analysis results.
    
    Args:
        result: Analysis result
        source: Data source
        symbol: BTC or ETH
        timeframe: Timeframe
        language: Report language
        captured_at: Capture timestamp
    
    Returns:
        Markdown formatted report
    """
    # Handle compare result
    if isinstance(result, CompareResult):
        # Use recommended result
        if result.recommended == "llm" and result.llm_result:
            analysis = result.llm_result
        else:
            analysis = result.algo_result
        mode_used = f"{result.recommended} (recommended: {result.recommendation_reason})"
    else:
        analysis = result
        mode_used = result.mode_used

    template = TEMPLATE_ZH if language == "zh" else TEMPLATE_EN
    disclaimer = DISCLAIMER_ZH if language == "zh" else DISCLAIMER_EN

    # Generate levels section
    levels_section = _format_levels(analysis.levels, analysis.current_price, language)
    
    # Generate summary
    summary = _format_summary(analysis.levels, analysis.current_price, language)
    
    # Generate magnet paths
    magnet_paths = _format_magnet_paths(analysis.levels, analysis.current_price, language)
    
    # Generate risk factors
    risk_factors = _format_risk_factors(analysis, language)

    report = template.format(
        symbol=symbol,
        source=source.capitalize(),
        timeframe=timeframe,
        captured_at=captured_at or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        current_price=analysis.current_price or 0,
        mode_used=mode_used,
        confidence=analysis.confidence_overall,
        levels_section=levels_section,
        summary=summary,
        magnet_paths=magnet_paths,
        risk_factors=risk_factors,
        disclaimer=disclaimer,
    )

    return report


def _format_levels(
    levels: list[LiquidationLevel],
    current_price: Optional[float],
    language: str,
) -> str:
    """Format liquidation levels as a table."""
    if not levels:
        return "No significant liquidation levels detected." if language == "en" else "未检测到明显的清算区间。"

    if language == "zh":
        header = "| 方向 | 价格 | 区间范围 | 强度 | 置信度 | 说明 |\n|------|------|----------|------|--------|------|\n"
    else:
        header = "| Side | Price | Range | Strength | Confidence | Evidence |\n|------|-------|-------|----------|------------|----------|\n"

    rows = []
    for level in levels:
        side_display = {
            "zh": {"above": "🔴 上方", "below": "🟢 下方"},
            "en": {"above": "🔴 Above", "below": "🟢 Below"},
        }
        
        side = side_display[language].get(level.side, level.side)
        price = f"${level.price:,.2f}" if level.price else "N/A"
        band = f"${level.band[0]:,.2f} - ${level.band[1]:,.2f}" if level.band[0] else "N/A"
        strength = f"{level.strength:.0%}"
        confidence = f"{level.confidence:.0%}"
        evidence = level.evidence[:50] + "..." if len(level.evidence) > 50 else level.evidence
        
        rows.append(f"| {side} | {price} | {band} | {strength} | {confidence} | {evidence} |")

    return header + "\n".join(rows)


def _format_summary(
    levels: list[LiquidationLevel],
    current_price: Optional[float],
    language: str,
) -> str:
    """Generate analysis summary."""
    if not levels:
        if language == "zh":
            return "当前图表中未检测到明显的清算聚集区域。"
        return "No significant liquidation clusters detected in the current chart."

    above_levels = [l for l in levels if l.side == "above"]
    below_levels = [l for l in levels if l.side == "below"]
    
    if language == "zh":
        parts = []
        
        if above_levels:
            strongest_above = max(above_levels, key=lambda x: x.strength)
            parts.append(f"- **上方阻力**: 在 ${strongest_above.price:,.2f} 附近存在较强清算聚集 (强度 {strongest_above.strength:.0%})")
        
        if below_levels:
            strongest_below = max(below_levels, key=lambda x: x.strength)
            parts.append(f"- **下方支撑**: 在 ${strongest_below.price:,.2f} 附近存在较强清算聚集 (强度 {strongest_below.strength:.0%})")
        
        if current_price:
            if above_levels and below_levels:
                nearest_above = min(above_levels, key=lambda x: abs(x.price - current_price))
                nearest_below = min(below_levels, key=lambda x: abs(x.price - current_price))
                dist_above = (nearest_above.price - current_price) / current_price * 100
                dist_below = (current_price - nearest_below.price) / current_price * 100
                parts.append(f"- **距离**: 上方最近清算区 {dist_above:.1f}%，下方最近清算区 {dist_below:.1f}%")
        
        return "\n".join(parts) if parts else "分析数据不足。"
    else:
        parts = []
        
        if above_levels:
            strongest_above = max(above_levels, key=lambda x: x.strength)
            parts.append(f"- **Resistance above**: Strong liquidation cluster near ${strongest_above.price:,.2f} (strength {strongest_above.strength:.0%})")
        
        if below_levels:
            strongest_below = max(below_levels, key=lambda x: x.strength)
            parts.append(f"- **Support below**: Strong liquidation cluster near ${strongest_below.price:,.2f} (strength {strongest_below.strength:.0%})")
        
        if current_price:
            if above_levels and below_levels:
                nearest_above = min(above_levels, key=lambda x: abs(x.price - current_price))
                nearest_below = min(below_levels, key=lambda x: abs(x.price - current_price))
                dist_above = (nearest_above.price - current_price) / current_price * 100
                dist_below = (current_price - nearest_below.price) / current_price * 100
                parts.append(f"- **Distance**: Nearest liquidation above {dist_above:.1f}%, below {dist_below:.1f}%")
        
        return "\n".join(parts) if parts else "Insufficient analysis data."


def _format_magnet_paths(
    levels: list[LiquidationLevel],
    current_price: Optional[float],
    language: str,
) -> str:
    """Generate potential price magnet path analysis."""
    if not levels or not current_price:
        if language == "zh":
            return "数据不足，无法分析价格磁吸路径。"
        return "Insufficient data to analyze price magnet paths."

    above_levels = sorted([l for l in levels if l.side == "above"], key=lambda x: x.price)
    below_levels = sorted([l for l in levels if l.side == "below"], key=lambda x: x.price, reverse=True)

    if language == "zh":
        parts = []
        
        if above_levels:
            targets = [f"${l.price:,.0f}" for l in above_levels[:3]]
            parts.append(f"- **向上路径**: 当前价格 → {' → '.join(targets)}")
            parts.append(f"  - 突破后可能触发连环清算，加速上涨")
        
        if below_levels:
            targets = [f"${l.price:,.0f}" for l in below_levels[:3]]
            parts.append(f"- **向下路径**: 当前价格 → {' → '.join(targets)}")
            parts.append(f"  - 跌破后可能触发连环清算，加速下跌")
        
        return "\n".join(parts) if parts else "无明显磁吸路径。"
    else:
        parts = []
        
        if above_levels:
            targets = [f"${l.price:,.0f}" for l in above_levels[:3]]
            parts.append(f"- **Upward path**: Current → {' → '.join(targets)}")
            parts.append(f"  - Breakout may trigger cascading liquidations, accelerating upward movement")
        
        if below_levels:
            targets = [f"${l.price:,.0f}" for l in below_levels[:3]]
            parts.append(f"- **Downward path**: Current → {' → '.join(targets)}")
            parts.append(f"  - Breakdown may trigger cascading liquidations, accelerating downward movement")
        
        return "\n".join(parts) if parts else "No clear magnet paths detected."


def _format_risk_factors(result: AnalysisResult, language: str) -> str:
    """Generate risk factors section."""
    if language == "zh":
        factors = [
            f"- 分析置信度: {result.confidence_overall:.0%}",
        ]
        
        if result.confidence_overall < 0.5:
            factors.append("- ⚠️ 置信度较低，建议结合其他指标验证")
        
        if result.errors:
            factors.append(f"- 分析过程中的警告: {'; '.join(result.errors[:3])}")
        
        factors.extend([
            "- 清算热力图为历史订单数据的可视化，不代表实时状态",
            "- 大户可能在关键位置设置止损单，形成虚假信号",
            "- 市场可能在未触及清算区前反转",
        ])
        
        return "\n".join(factors)
    else:
        factors = [
            f"- Analysis confidence: {result.confidence_overall:.0%}",
        ]
        
        if result.confidence_overall < 0.5:
            factors.append("- ⚠️ Low confidence - verify with other indicators")
        
        if result.errors:
            factors.append(f"- Analysis warnings: {'; '.join(result.errors[:3])}")
        
        factors.extend([
            "- Liquidation heatmaps show historical order data, not real-time positions",
            "- Large players may set stop losses at key levels, creating false signals",
            "- Market may reverse before reaching liquidation zones",
        ])
        
        return "\n".join(factors)
