#![allow(unused_mut,unused_variables)]
use std::{hint::black_box,time::Instant};
#[derive(serde::Deserialize,serde::Serialize)]
struct Field<const N:usize> {#[serde(with="faster_hex::array")]bytes:[u8;N]}
fn measure<const N:usize>(kind:&str,n:usize,count:usize)->f64{
 let expected:Vec<u8>=(0..n).map(|i|(37*i+11)as u8).collect();
 let digits=expected.iter().map(|b|format!("{b:02x}")).collect::<String>();
 let alt=expected.iter().enumerate().map(|(i,b)| if i%3==0{format!("{b:02X}")}else{format!("{b:02x}")}).collect::<String>();
 let canonical=format!(r#"{{"bytes":"0x{digits}"}}"#);
 let json=if kind=="escaped"{format!(r#"{{"bytes":"\u0030x{alt}"}}"#)}else{format!(r#"{{"bytes":"0x{alt}"}}"#)};
 let mut dst=Vec::<u8>::with_capacity(canonical.len());
 assert_eq!(N,n);{let value:Field<N>=serde_json::from_slice(black_box(json.as_bytes())).unwrap();assert_eq!(value.bytes.as_slice(),expected.as_slice());assert_eq!(serde_json::to_vec(&value).unwrap(),canonical.as_bytes());}
 let start=Instant::now();for _ in 0..count{let value:Field<N>=serde_json::from_slice(black_box(json.as_bytes())).unwrap();dst.clear();serde_json::to_writer(&mut dst,&value).unwrap();black_box(dst.as_slice());}
 start.elapsed().as_nanos()as f64/count as f64
}
fn main(){let a:Vec<_>=std::env::args().collect();let n=a[1].parse().unwrap();let k:usize=a[2].parse().unwrap();let kind=a[3].as_str();let run=|k|match n{32=>measure::<32>(kind,n,k),4096=>measure::<4096>(kind,n,k),_=>unreachable!()};black_box(run((k/6).max(16)));println!("{:.6}",run(k));}
