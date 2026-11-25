"""Shared pricing engine: statistics and benchmarks over observed prices (pure, no I/O).

Advertised prices (price_observations) and completed sales (observed_sales) are summarized by
different functions into different result types. Nothing here invents a price: too little data
yields an explicit INSUFFICIENT_DATA / NO_DATA status instead of numbers.
"""
