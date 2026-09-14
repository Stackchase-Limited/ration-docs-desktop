// The current core signature: core commit a84491cf74 made pDataSrc const.
typedef unsigned char BYTE; typedef unsigned long DWORD;
namespace NSFile {
class CBase64Converter {
public:
	static bool Encode(const BYTE* pDataSrc, int nLenSrc, char*& pDataDst, int& nLenDst, DWORD dwFlags = 0);
};
bool CBase64Converter::Encode(const BYTE*, int, char*&, int&, DWORD) { return true; }
}
