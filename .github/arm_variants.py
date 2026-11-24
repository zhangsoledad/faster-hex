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
