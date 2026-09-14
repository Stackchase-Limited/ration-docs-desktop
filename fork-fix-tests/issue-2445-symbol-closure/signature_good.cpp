// The same module rebuilt against the current header.
typedef unsigned char BYTE; typedef unsigned long DWORD;
namespace NSFile {
class CBase64Converter {
public:
	static bool Encode(const BYTE* pDataSrc, int nLenSrc, char*& pDataDst, int& nLenDst, DWORD dwFlags = 0);
};
}
extern "C" bool sign(BYTE* p, int n) { char* d = 0; int dl = 0; return NSFile::CBase64Converter::Encode(p, n, d, dl, 0); }
