!function(){
    var _0x1a2b=["AES","encrypt","Utf8","parse","toString","#total_price","#paymentForm","addEventListener","submit","value"];
    
    // Keys with CinemaMax included
    var keyStr=_0x1a2b[3]("CinemaMaxSecretKey!"), 
        ivStr=_0x1a2b[3]("CinemaMaxIV123456"); 
    
    function _0xencodePrice(_0xprice){
        return CryptoJS[_0x1a2b[0]][_0x1a2b[1]](_0xprice.toString(), keyStr, {iv: ivStr})[_0x1a2b[4]]();
    }
    
    document.querySelector(_0x1a2b[5])[_0x1a2b[7]](_0x1a2b[8], function(_0xe){
        var _0xinput=document.querySelector(_0x1a2b[6]);
        _0xinput[_0x1a2b[9]]=_0xencodePrice(_0xinput[_0x1a2b[9]]);
    });
}();
