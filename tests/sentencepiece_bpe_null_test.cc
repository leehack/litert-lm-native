#include "sentencepiece_model.pb.h"
#include "sentencepiece_processor.h"
#include <cstdio>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
using namespace sentencepiece;
void require(bool ok, const char *msg) {
  if (!ok)
    throw std::runtime_error(msg);
}
int main(int argc, char **argv) {
  require(argc == 2, "tokenizer argument required");
  ModelProto proto;
  std::ifstream f(argv[1], std::ios::binary);
  require(proto.ParseFromIstream(&f), "parse");
  SentencePieceProcessor sp;
  require(sp.Load(proto).ok(), "load untouched Qwen");
  require(sp.GetPieceSize() == 151669, "vocab count");
  for (int i = 0; i < sp.GetPieceSize(); ++i) {
    require(sp.IdToPiece(i) == proto.pieces(i).piece(), "id mapping");
    require(sp.PieceToId(sp.IdToPiece(i)) == i, "piece mapping");
  }
  require(sp.IdToPiece(188) == std::string(1, '\0'), "NUL id");
  std::vector<std::string> corpus = {
      "What is 2+2? Answer only with the number.",
      "Bonjour Montréal 世界 한국어 👋",
      "  a\t b\n",
      std::string("a\0b", 3),
      std::string("\0a", 2),
      std::string("a\0", 2),
      std::string(2, '\0'),
      std::string("\xff\xfe", 2),
      "<|im_start|>user\nHello<|im_end|>"};
  for (const auto &text : corpus) {
    std::vector<int> ids;
    require(sp.Encode(text, &ids).ok(), "encode");
    std::string decoded;
    require(sp.Decode(ids, &decoded).ok(), "decode");
    for (int id : ids)
      std::cout << id << ',';
    std::cout << ' ';
    for (unsigned char c : decoded)
      std::cout << std::hex << std::setw(2) << std::setfill('0') << (int)c;
    std::cout << std::dec << '\n';
  }
  {
    auto m = proto;
    auto *symbol = m.add_pieces();
    symbol->set_piece("<null-probe>");
    symbol->set_type(ModelProto::SentencePiece::USER_DEFINED);
    SentencePieceProcessor mixed;
    require(mixed.Load(m).ok(), "BPE with user-defined trie");
    std::vector<int> ids;
    require(mixed.Encode(std::string(1, '\0'), &ids).ok(), "mixed encode");
    require(ids == std::vector<int>{188}, "mixed NUL id");
  }
  int negatives = 0;
  auto reject = [&](ModelProto model) {
    SentencePieceProcessor bad;
    require(!bad.Load(model).ok(), "negative accepted");
    ++negatives;
  };
  for (const auto &value : {std::string("a\0", 2), std::string("\0a", 2),
                            std::string("a\0b", 3), std::string(2, '\0')}) {
    auto m = proto;
    m.mutable_pieces(188)->set_piece(value);
    reject(m);
  }
  for (auto type :
       {ModelProto::SentencePiece::UNKNOWN, ModelProto::SentencePiece::CONTROL,
        ModelProto::SentencePiece::USER_DEFINED,
        ModelProto::SentencePiece::UNUSED, ModelProto::SentencePiece::BYTE}) {
    auto m = proto;
    m.mutable_pieces(188)->set_type(type);
    reject(m);
  }
  for (auto type :
       {TrainerSpec::UNIGRAM, TrainerSpec::WORD, TrainerSpec::CHAR}) {
    auto m = proto;
    m.mutable_trainer_spec()->set_model_type(type);
    reject(m);
  }
  {
    auto m = proto;
    *m.add_pieces() = proto.pieces(188);
    reject(m);
  }
  {
    auto m = proto;
    m.mutable_pieces(188)->set_piece("");
    reject(m);
  }
  {
    auto m = proto;
    m.mutable_pieces(188)->set_piece(std::string(8000, 'a'));
    reject(m);
  }
  {
    auto m = proto;
    m.mutable_trainer_spec()->set_byte_fallback(true);
    for (int byte = 0; byte < 256; ++byte) {
      char name[7];
      std::snprintf(name, sizeof(name), "<0x%02X>", byte);
      auto *piece = m.add_pieces();
      piece->set_piece(name);
      piece->set_type(ModelProto::SentencePiece::BYTE);
    }
    auto valid = m;
    valid.mutable_pieces(188)->set_piece("<null-probe>");
    SentencePieceProcessor byte_model;
    require(byte_model.Load(valid).ok(), "valid byte-fallback baseline");
    reject(m);
  }
  std::cerr << "PASS: 151669 token mappings, " << corpus.size()
            << " corpus cases, " << negatives << " rejection cases\n";
}
