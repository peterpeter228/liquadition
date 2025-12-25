"""
Report generation for liquidation heatmap analysis.
"""

from datetime import datetime, timezone
from typing import Literal, Optional


def generate_report(
    analysis_result: dict,
    source: str,
    symbol: str,
    timeframe: str,
    language: Literal["zh", "en"] = "en",
    debug_info: Optional[dict] = None,
) -> str:
    """
    Generate a markdown report from analysis results.
    
    Args:
        analysis_result: The result from analyze_heatmap
        source: Data source (coinank/coinglass)
        symbol: Trading symbol
        timeframe: Chart timeframe
        language: Report language
        debug_info: Optional debug information to include
    
    Returns:
        Markdown formatted report
    """
    if language == "zh":
        return _generate_zh_report(analysis_result, source, symbol, timeframe, debug_info)
    else:
        return _generate_en_report(analysis_result, source, symbol, timeframe, debug_info)


def _generate_en_report(
    result: dict,
    source: str,
    symbol: str,
    timeframe: str,
    debug_info: Optional[dict],
) -> str:
    """Generate English report."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    
    # Handle compare mode
    if "comparison" in result:
        main_result = result.get("algo_result", {}) if result["comparison"]["recommended"] == "algo" else result.get("llm_result", {})
        levels = main_result.get("levels", [])
        current_price = main_result.get("current_price")
        mode_used = result["comparison"]["recommended"]
    else:
        levels = result.get("levels", [])
        current_price = result.get("current_price")
        mode_used = result.get("mode_used", "unknown")
    
    lines = [
        f"# {symbol}/USDT Liquidation Heatmap Analysis",
        "",
        f"**Source:** {source.capitalize()}  ",
        f"**Timeframe:** {timeframe}  ",
        f"**Analysis Mode:** {mode_used}  ",
        f"**Generated:** {timestamp}",
        "",
    ]
    
    if current_price:
        lines.extend([
            f"## Current Price",
            f"**{symbol}/USDT:** ${current_price:,.2f}",
            "",
        ])
    
    lines.extend([
        "## Key Liquidation Levels",
        "",
    ])
    
    if not levels:
        lines.append("*No significant liquidation levels detected.*")
    else:
        # Separate above and below
        above_levels = [l for l in levels if l.get("side") == "above"]
        below_levels = [l for l in levels if l.get("side") == "below"]
        
        if above_levels:
            lines.extend([
                "### Resistance Levels (Above Current Price)",
                "",
                "| Price | Band | Strength | Confidence |",
                "|-------|------|----------|------------|",
            ])
            for level in sorted(above_levels, key=lambda x: x["price"]):
                band_str = f"${level['band'][0]:,.0f} - ${level['band'][1]:,.0f}"
                strength_bar = "█" * int(level["strength"] * 5) + "░" * (5 - int(level["strength"] * 5))
                lines.append(
                    f"| ${level['price']:,.2f} | {band_str} | {strength_bar} {level['strength']:.0%} | {level['confidence']:.0%} |"
                )
            lines.append("")
        
        if below_levels:
            lines.extend([
                "### Support Levels (Below Current Price)",
                "",
                "| Price | Band | Strength | Confidence |",
                "|-------|------|----------|------------|",
            ])
            for level in sorted(below_levels, key=lambda x: x["price"], reverse=True):
                band_str = f"${level['band'][0]:,.0f} - ${level['band'][1]:,.0f}"
                strength_bar = "█" * int(level["strength"] * 5) + "░" * (5 - int(level["strength"] * 5))
                lines.append(
                    f"| ${level['price']:,.2f} | {band_str} | {strength_bar} {level['strength']:.0%} | {level['confidence']:.0%} |"
                )
            lines.append("")
    
    # Potential paths
    lines.extend([
        "## Potential Price Movement",
        "",
    ])
    
    if levels and current_price:
        nearest_above = min([l for l in levels if l.get("side") == "above"], 
                          key=lambda x: x["price"], default=None) if above_levels else None
        nearest_below = max([l for l in levels if l.get("side") == "below"],
                          key=lambda x: x["price"], default=None) if below_levels else None
        
        if nearest_above:
            dist_above = ((nearest_above["price"] - current_price) / current_price) * 100
            lines.append(f"- **Upward Target:** ${nearest_above['price']:,.2f} ({dist_above:+.1f}%) - Strength: {nearest_above['strength']:.0%}")
        
        if nearest_below:
            dist_below = ((nearest_below["price"] - current_price) / current_price) * 100
            lines.append(f"- **Downward Target:** ${nearest_below['price']:,.2f} ({dist_below:+.1f}%) - Strength: {nearest_below['strength']:.0%}")
        
        lines.append("")
        lines.append("**Note:** High liquidation concentration zones may act as \"magnets\" attracting price movement.")
    else:
        lines.append("*Insufficient data to determine potential price paths.*")
    
    lines.append("")
    
    # Risk assessment
    confidence = result.get("confidence_overall", 0)
    if "comparison" in result:
        confidence = main_result.get("confidence_overall", 0)
    
    lines.extend([
        "## Analysis Quality",
        "",
        f"- **Overall Confidence:** {confidence:.0%}",
    ])
    
    errors = result.get("errors") or main_result.get("errors") if "comparison" in result else result.get("errors")
    if errors:
        lines.append(f"- **Warnings:** {', '.join(errors)}")
    
    lines.append("")
    
    # Debug info
    if debug_info:
        lines.extend([
            "## Debug Information",
            "",
            f"- **Crop Method:** {debug_info.get('method', 'N/A')}",
            f"- **Crop Rect:** {debug_info.get('crop_rect', 'N/A')}",
        ])
        
        latency = result.get("latency_ms", {})
        if "comparison" in result:
            latency = main_result.get("latency_ms", {})
        if latency:
            lines.append(f"- **Latency:** {latency}")
        lines.append("")
    
    # Disclaimer
    lines.extend([
        "---",
        "",
        "⚠️ **DISCLAIMER:** This analysis is for informational purposes only and does not constitute investment advice. "
        "Liquidation heatmaps show historical data and potential future liquidation zones, but do not guarantee price movement. "
        "Always conduct your own research and manage risk appropriately. Trading cryptocurrencies carries significant risk of loss.",
        "",
    ])
    
    return "\n".join(lines)


def _generate_zh_report(
    result: dict,
    source: str,
    symbol: str,
    timeframe: str,
    debug_info: Optional[dict],
) -> str:
    """Generate Chinese report."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    
    # Handle compare mode
    if "comparison" in result:
        main_result = result.get("algo_result", {}) if result["comparison"]["recommended"] == "algo" else result.get("llm_result", {})
        levels = main_result.get("levels", [])
        current_price = main_result.get("current_price")
        mode_used = result["comparison"]["recommended"]
    else:
        levels = result.get("levels", [])
        current_price = result.get("current_price")
        mode_used = result.get("mode_used", "unknown")
    
    mode_name = "算法分析" if mode_used == "algo" else "AI分析"
    
    lines = [
        f"# {symbol}/USDT 清算热力图分析",
        "",
        f"**数据源:** {source.capitalize()}  ",
        f"**时间周期:** {timeframe}  ",
        f"**分析模式:** {mode_name}  ",
        f"**生成时间:** {timestamp}",
        "",
    ]
    
    if current_price:
        lines.extend([
            f"## 当前价格",
            f"**{symbol}/USDT:** ${current_price:,.2f}",
            "",
        ])
    
    lines.extend([
        "## 关键清算位置",
        "",
    ])
    
    if not levels:
        lines.append("*未检测到显著的清算位置。*")
    else:
        above_levels = [l for l in levels if l.get("side") == "above"]
        below_levels = [l for l in levels if l.get("side") == "below"]
        
        if above_levels:
            lines.extend([
                "### 上方阻力位（高于当前价格）",
                "",
                "| 价格 | 区间 | 强度 | 置信度 |",
                "|------|------|------|--------|",
            ])
            for level in sorted(above_levels, key=lambda x: x["price"]):
                band_str = f"${level['band'][0]:,.0f} - ${level['band'][1]:,.0f}"
                strength_bar = "█" * int(level["strength"] * 5) + "░" * (5 - int(level["strength"] * 5))
                lines.append(
                    f"| ${level['price']:,.2f} | {band_str} | {strength_bar} {level['strength']:.0%} | {level['confidence']:.0%} |"
                )
            lines.append("")
        
        if below_levels:
            lines.extend([
                "### 下方支撑位（低于当前价格）",
                "",
                "| 价格 | 区间 | 强度 | 置信度 |",
                "|------|------|------|--------|",
            ])
            for level in sorted(below_levels, key=lambda x: x["price"], reverse=True):
                band_str = f"${level['band'][0]:,.0f} - ${level['band'][1]:,.0f}"
                strength_bar = "█" * int(level["strength"] * 5) + "░" * (5 - int(level["strength"] * 5))
                lines.append(
                    f"| ${level['price']:,.2f} | {band_str} | {strength_bar} {level['strength']:.0%} | {level['confidence']:.0%} |"
                )
            lines.append("")
    
    # Potential paths
    lines.extend([
        "## 潜在价格走势",
        "",
    ])
    
    if levels and current_price:
        above_levels = [l for l in levels if l.get("side") == "above"]
        below_levels = [l for l in levels if l.get("side") == "below"]
        
        nearest_above = min(above_levels, key=lambda x: x["price"], default=None) if above_levels else None
        nearest_below = max(below_levels, key=lambda x: x["price"], default=None) if below_levels else None
        
        if nearest_above:
            dist_above = ((nearest_above["price"] - current_price) / current_price) * 100
            lines.append(f"- **向上目标:** ${nearest_above['price']:,.2f} ({dist_above:+.1f}%) - 强度: {nearest_above['strength']:.0%}")
        
        if nearest_below:
            dist_below = ((nearest_below["price"] - current_price) / current_price) * 100
            lines.append(f"- **向下目标:** ${nearest_below['price']:,.2f} ({dist_below:+.1f}%) - 强度: {nearest_below['strength']:.0%}")
        
        lines.append("")
        lines.append('**注意:** 高清算集中区可能像"磁铁"一样吸引价格移动。')
    else:
        lines.append("*数据不足，无法判断潜在价格路径。*")
    
    lines.append("")
    
    # Analysis quality
    confidence = result.get("confidence_overall", 0)
    if "comparison" in result:
        confidence = main_result.get("confidence_overall", 0)
    
    lines.extend([
        "## 分析质量",
        "",
        f"- **总体置信度:** {confidence:.0%}",
    ])
    
    errors = result.get("errors") or main_result.get("errors") if "comparison" in result else result.get("errors")
    if errors:
        lines.append(f"- **警告:** {', '.join(errors)}")
    
    lines.append("")
    
    # Debug info
    if debug_info:
        lines.extend([
            "## 调试信息",
            "",
            f"- **裁剪方法:** {debug_info.get('method', 'N/A')}",
            f"- **裁剪区域:** {debug_info.get('crop_rect', 'N/A')}",
        ])
        
        latency = result.get("latency_ms", {})
        if "comparison" in result:
            latency = main_result.get("latency_ms", {})
        if latency:
            lines.append(f"- **延迟:** {latency}")
        lines.append("")
    
    # Disclaimer
    lines.extend([
        "---",
        "",
        "⚠️ **免责声明:** 本分析仅供参考，不构成任何投资建议。清算热力图显示的是历史数据和潜在的未来清算区域，"
        "但不保证价格一定会如此波动。请务必进行自己的研究，合理管理风险。加密货币交易具有重大的亏损风险。",
        "",
    ])
    
    return "\n".join(lines)
