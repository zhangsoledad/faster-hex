"""Vary only the block scan used to locate an error after hex_validate rejects input."""
def code(s, mode):
    if mode=="unchanged":return s
    if mode=="legacy":
        return s.replace(".take_while(|chunk| check_mixed(chunk))",".take_while(|chunk| crate::hex_check(chunk))")
    original="""        src.chunks_exact(CHUNK)
            .take_while(|chunk| check_mixed(chunk))
            .count()
            * CHUNK"""
    assert s.count(original)==1
    anchor="#[cfg(any(target_arch = \"x86\", target_arch = \"x86_64\"))]\n#[inline]\n#[target_feature(enable = \"sse2\")]"
    assert s.count(anchor)==1
    if mode=="outline":
        helper="""// The first failing block is enough to start scalar diagnosis.
#[inline(never)]
fn valid_prefix_len<const N: usize>(src: &[u8]) -> usize {
    src.as_chunks::<N>().0.iter().take_while(|block| check_mixed(*block)).count() * N
}

"""
        return s.replace(original,"        valid_prefix_len::<CHUNK>(src)").replace(anchor,helper+anchor)
    if mode in ("direct","outdirect"):
        a=s.index("        let a = valid_neon_mixed(vld1q_u8(batch.as_ptr()));")
        b=s.index("            return false;",a)
        body=s[a:b];last=body.index("        if vminvq")
        predicate=body[:last].replace("        ","    ")+body[last:].strip().removeprefix("if ").removesuffix(" == 0 {")+" != 0"
        helper='''#[cfg(target_arch = "aarch64")]
#[inline]
#[target_feature(enable = "neon")]
unsafe fn valid_neon_block(batch: &[u8; 64]) -> bool {
'''+predicate+'''
}

'''
        marker='#[cfg(target_arch = "aarch64")]\n#[inline]\n#[target_feature(enable = "neon")]\nunsafe fn check_mixed_neon(src:'
        assert s.count(marker)==1
        s=s[:a]+"        if !valid_neon_block(batch) {\n"+s[b:]
        s=s.replace(marker,helper+marker)
        helper='''// Reuse the fixed-width classifier when NEON is part of the target baseline.
#[inline]
fn valid_diagnostic_block(block: &[u8; 64]) -> bool {
    #[cfg(all(target_arch = "aarch64", target_feature = "neon", not(miri)))]
    {
        // SAFETY: The target guarantees NEON and the array covers every load.
        unsafe { valid_neon_block(block) }
    }
    #[cfg(not(all(target_arch = "aarch64", target_feature = "neon", not(miri))))]
    check_mixed(block)
}

'''
        s=s.replace(anchor,helper+anchor)
        body="src.as_chunks::<CHUNK>().0.iter().take_while(|block| valid_diagnostic_block(block)).count() * CHUNK"
        if mode=="direct":return s.replace(original,"        "+body)
        helper='''#[inline(never)]
fn valid_prefix_len<const CHUNK: usize>(src: &[u8]) -> usize {
    src.as_chunks::<64>().0.iter().take_while(|block| valid_diagnostic_block(block)).count() * 64
}

'''
        return s.replace(original,"        valid_prefix_len::<CHUNK>(src)").replace(anchor,helper+anchor)
    raise ValueError(mode)

def apply_one_pass(validate, entry, mode):
    # Retain each failing block's original offset in the first NEON scan.
    s=code(validate,"direct")
    helper_start=s.index("// Reuse the fixed-width classifier")
    helper_end=s.index('#[cfg(any(target_arch = "x86"',helper_start)
    s=s[:helper_start]+s[helper_end:]
    s=s.replace("src.as_chunks::<CHUNK>().0.iter().take_while(|block| valid_diagnostic_block(block)).count() * CHUNK",
                "src.chunks_exact(CHUNK).take_while(|block| check_mixed(block)).count() * CHUNK")
    marker='#[cfg(target_arch = "aarch64")]\n#[inline]\n#[target_feature(enable = "neon")]\nunsafe fn check_mixed_neon(src:'
    routine='''#[cfg(all(target_arch = "aarch64", target_feature = "neon", not(miri)))]
#[inline]
#[target_feature(enable = "neon")]
pub(super) unsafe fn validate_neon_blocks<const WIDTH: usize>(src: &[u8]) -> Result<(), Error> {
    let (blocks, tail) = src.as_chunks::<64>();
    for (i, block) in blocks.iter().enumerate() {
        if !valid_neon_block(block) {
            return diagnose_block::<WIDTH>(block, i * 64);
        }
    }
    if tail.is_empty() || check_mixed_neon_short(tail) {
        Ok(())
    } else {
        diagnose_block::<WIDTH>(tail, src.len() - tail.len())
    }
}

#[cfg(all(target_arch = "aarch64", target_feature = "neon", not(miri)))]
#[cold]
#[inline(never)]
fn diagnose_block<const WIDTH: usize>(block: &[u8], offset: usize) -> Result<(), Error> {
    for (i, &byte) in block.iter().enumerate() {
        if UNHEX[usize::from(byte)] == NIL {
            return Err(Error::InvalidChar { index: offset + i, byte });
        }
    }
    Ok(())
}

'''
    if mode=="all_neon":
        needle="    let (blocks, tail) = src.as_chunks::<64>();"
        routine=routine.replace(needle,"    if src.len() < 64 {\n        return if check_mixed_neon_short(src) { Ok(()) } else { diagnose_block::<WIDTH>(src, 0) };\n    }\n"+needle)
    s=s.replace(marker,routine+marker)
    begin=entry.index("    if validate::check_mixed(src) {")
    end=entry.index("\n}",begin)
    old=entry[begin:end]
    cfg='all(target_arch = "aarch64", target_feature = "neon", not(miri))'
    if mode=="onepass":
        new=f"    #[cfg({cfg})]\n    if src.len() >= 64 {{\n        // SAFETY: NEON is guaranteed by the target.\n        return unsafe {{ validate::validate_neon_blocks::<64>(src) }};\n    }}\n"+old
    else:
        new=f"    #[cfg({cfg})]\n    {{\n        // SAFETY: NEON is guaranteed by the target.\n        unsafe {{ validate::validate_neon_blocks::<64>(src) }}\n    }}\n    #[cfg(not({cfg}))]\n    {{\n"+old+"\n    }"
    return s,entry[:begin]+new+entry[end:]
