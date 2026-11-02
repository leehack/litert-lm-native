"""Independent audit's 19 single mutations plus its combined confidence bypass.

Keep the literal substitutions reviewable and fail on source drift. These
mutate only temporary real C++ sources, never the shipped patch/provenance.
"""

AUDIT_MUTATIONS = {
    'U1_no_offset_consistency': (
        'if (alignment.has_value() && *alignment != start - skip) ambiguous = true;',
        '',
    ),
    'U2_no_uniqueness': (
        'if (matches != 1) ambiguous = true;',
        '',
    ),
    'U3_no_short_tolerant': (
        'best_length < 3) ambiguous = true;\n    // Low',
        'false) ambiguous = true;\n    // Low',
    ),
    'U4_distinct_floor_2': (
        'distinct < 6 ||',
        'distinct < 2 ||',
    ),
    'U5_no_half_distinct': (
        '|| distinct * 2 <= static_cast<int>(words->size())',
        '',
    ),
    'U6_no_repeated_bigram_short': (
        'if (repeated > 0 && best_length < 3) ambiguous = true;',
        '',
    ),
    'U7_no_repeated_half': (
        'if (repeated * 2 >= static_cast<int>(words->size())) ambiguous = true;',
        '',
    ),
    'U8_no_skip_shared': (
        'if (std::find(prev.begin(), prev.end(), curr[i]) != prev.end())\n          ambiguous = true;',
        '',
    ),
    'U9_no_trim_shared': (
        'if (std::find(curr.begin(), curr.end(), prev[i]) != curr.end())\n          ambiguous = true;',
        '',
    ),
    'U10_earliest_zero_floor': (
        'int earliest = std::max(1, static_cast<int>(',
        'int earliest = std::max(0, static_cast<int>(',
    ),
    'U11_no_search_window_slack': (
        'prev.size() * (1 - overlap_ratio_)) - search_window_);',
        'prev.size() * (1 - overlap_ratio_)));',
    ),
    'U12_no_skip': (
        'skip <= 2',
        'skip <= 0',
    ),
    'U13_no_trim': (
        'trim <= 1',
        'trim <= 0',
    ),
    'U14_skip3': (
        'skip <= 2',
        'skip <= 3',
    ),
    'U15_new_spelling': (
        'std::vector<std::string> merged(prev_words_.begin() + best_start,\n                                      prev_words_.begin() + best_end);',
        'std::vector<std::string> merged(curr_words.begin() + best_skip,\n                                      curr_words.begin() + best_skip + best_length);',
    ),
    'U16_ties_prefer_later': (
        'if (length <= best_length) continue;',
        'if (length < best_length) continue;',
    ),
    'U17_distinct_floor_4': (
        'distinct < 6 ||',
        'distinct < 4 ||',
    ),
    'U18_no_uniqueness_in_curr': (
        'for (const auto* words : {&prev, &curr}) {\n        int matches = 0;',
        'for (const auto* words : {&prev}) {\n        int matches = 0;',
    ),
    'U19_dedup_continuation': (
        'merged.insert(merged.end(), curr_words.begin() + best_skip + best_length,\n                    curr_words.end());',
        'merged.insert(merged.end(), curr_words.begin() + best_skip + best_length,\n                    curr_words.end());\n      merged.erase(std::unique(merged.begin(), merged.end()), merged.end());',
    ),
}
