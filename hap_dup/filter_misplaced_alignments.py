#!/usr/bin/env python3

#Script to filter out possibly mismapped alignments in sam

import sys
import re
from collections import namedtuple, defaultdict
import subprocess


ReadSegment = namedtuple("ReadSegment", ["read_start", "read_end", "ref_start", "ref_end", "read_id", "ref_id",
                                         "strand", "read_length", "mismatch_rate"])


def get_segment(read_id, ref_id, ref_start, strand, cigar, num_mismatch):
    first_clip = False
    read_start = 0
    read_aligned = 0
    read_length = 0
    ref_aligned = 0
    #read_end = 0

    for token in re.findall("[\d]{0,}[A-Z]{1}", cigar):
        op = token[-1]
        op_len = int(token[:-1])

        if op in "HS":
            if not first_clip:
                first_clip = True
                read_start = op_len
            read_length += op_len

        if op in "M=X":
            read_aligned += op_len
            ref_aligned += op_len
            read_length += op_len
        if op == "D":
            ref_aligned += op_len
        if op == "I":
            read_aligned += op_len
            read_length += op_len

    ref_end = ref_start + ref_aligned
    read_end = read_start + read_aligned

    #mm_rate = num_mismatch / (read_aligned + 1)
    length_diff = abs(ref_aligned - read_aligned)
    mm_rate = (num_mismatch - length_diff) / (read_aligned + 1)

    #print(read_id, mm_rate, mm_rate_2)

    if strand == "-":
        read_start, read_end = read_length - read_end, read_length - read_start

    return ReadSegment(read_start, read_end, ref_start, ref_end, read_id,
                       ref_id, strand, read_length, mm_rate)


def check_read_mapping_confidence(sam_text_entry, min_aln_length, min_aligned_rate,
                                  max_read_error, max_segments):
    fields = sam_text_entry.split()

    read_id, flags, chr_id, position = fields[0:4]
    cigar = fields[5]
    ref_id, ref_start = fields[2], int(fields[3])

    is_supplementary = int(flags) & 0x800
    is_secondary = int(flags) & 0x100
    is_unmapped = int(flags) & 0x4
    strand = "-" if int(flags) & 0x10 else "+"

    if is_unmapped:
        return False

    sa_tag = ""
    num_mismatches = 0
    #de_tag = None
    for tag in fields[11:]:
        if tag.startswith("SA"):
            sa_tag = tag[5:]
        if tag.startswith("NM"):
            num_mismatches = int(tag[5:])
        #if tag.startswith("de"):
        #    de_tag = float(tag[5:])

    segments = [get_segment(read_id, ref_id, ref_start, strand, cigar, num_mismatches)]
    #print(de_tag, segments[0].mismatch_rate)
    if sa_tag:
        for sa_aln in sa_tag.split(";"):
            if sa_aln:
                sa_fields = sa_aln.split(",")
                sa_ref, sa_ref_pos, sa_strand, sa_cigar, sa_mismatches = \
                        sa_fields[0], int(sa_fields[1]), sa_fields[2], sa_fields[3], int(sa_fields[5])
                segments.append(get_segment(read_id, sa_ref, sa_ref_pos, sa_strand, sa_cigar, sa_mismatches))
    segments.sort(key=lambda s: s.read_start)

    read_length = segments[0].read_length

    WND_LEN = 100
    read_coverage = [0 for x in range(read_length // WND_LEN)]
    weighted_mm_sum = 0
    total_segment_length = 0
    for seg in segments:
        for i in range(seg.read_start // WND_LEN, seg.read_end // WND_LEN):
            read_coverage[i] = 1
        weighted_mm_sum += seg.mismatch_rate * (seg.read_end - seg.read_start)
        total_segment_length += seg.read_end - seg.read_start
    aligned_length = sum(read_coverage) * WND_LEN
    mean_mm = weighted_mm_sum / (total_segment_length + 1)

    if (is_secondary or 
            is_unmapped or 
            aligned_length < min_aln_length or 
            aligned_length / read_length < min_aligned_rate or
            len(segments) > max_segments or
            mean_mm > max_read_error):
        return False

    else:
        return True
        #if len(segments) > 1:
        #    print(read_length, len(segments), aligned_length, aligned_length / read_length, mean_mm)
        #if is_supplementary:
        #    new_read_id = read_id + "_suppl_" + str(unique_id)
        #    unique_id += 1
        #    new_flags = int(flags) & ~0x800
        #    aln.query_name = new_read_id
        #    aln.flag = new_flags


MIN_ALIGNED_LENGTH = 10000
MAX_SEGMENTS = 3
MIN_ALIGNED_RATE = 0.9
MAX_READ_ERROR = 0.1
SAMTOOLS = "flye-samtools"


def filter_alignments(bam_in, bam_out):
    bam_reader = subprocess.Popen(SAMTOOLS + " view -h -@4 " + bam_in, shell=True, stdout=subprocess.PIPE)
    bam_writer = subprocess.Popen(SAMTOOLS + " view - -b -1 -@4 -o " + bam_out, shell=True, stdin=subprocess.PIPE)
    for line in bam_reader.stdout:
        if line.startswith(b"@"):
            bam_writer.stdin.write(line)
            continue
        if check_read_mapping_confidence(line.decode("utf-8"), MIN_ALIGNED_LENGTH, MIN_ALIGNED_RATE, MAX_READ_ERROR, MAX_SEGMENTS):
            bam_writer.stdin.write(line)
    bam_reader.communicate()
    bam_writer.communicate()


def main():
    filter_alignments(sys.argv[1], sys.argv[2])
    #for line in sys.stdin:
    #    if line.startswith("@"):
    #        sys.stdout.write(line)
    #        continue
    #    if check_read_mapping_confidence(line, MIN_ALIGNED_LENGTH, MIN_ALIGNED_RATE, MAX_READ_ERROR, MAX_SEGMENTS):
    #        sys.stdout.write(line)


if __name__ == "__main__":
    main()


